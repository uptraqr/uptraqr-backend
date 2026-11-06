import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
from sqlalchemy import func

from app.services.safe_fetch import check_url_is_safe, UnsafeURLError, USER_AGENT
from app.core.database import SessionLocal
from app.core.plans import plan_for
from app.models.models import Monitor, CheckResult, Incident, User
from app.services.email_alerts import send_down_alert, send_recovery_alert
from app.services.sms_alerts import send_down_sms, send_recovery_sms

RETRY_DELAY = 5   # seconds to wait before re-checking a site that looked down
WORKERS = 10      # how many sites are checked at the same time


def _check_once(url: str):
    try:
        # Refuse private/internal addresses, and don't follow redirects blindly,
        # so a monitor can't be used to probe UpTraQR's own network (SSRF).
        check_url_is_safe(url)
        response = requests.get(url, timeout=10, allow_redirects=False, headers={"User-Agent": USER_AGENT})
        return {
            # A server error (500-599) means the site is broken even though it answered.
            "is_up": response.status_code < 500,
            "status_code": response.status_code,
            "response_time": response.elapsed.total_seconds(),
        }
    except (requests.exceptions.RequestException, UnsafeURLError):
        return {"is_up": False, "status_code": None, "response_time": None}


def check_url(url: str):
    """Check a site; if it looks down, wait a few seconds and look again before believing it."""
    result = _check_once(url)
    if not result["is_up"]:
        time.sleep(RETRY_DELAY)
        result = _check_once(url)
    return result


def _keyword_once(url: str, keyword: str):
    """Load the page (following safe redirects) and check the words are still there."""
    from app.services.safe_fetch import safe_get_detailed
    try:
        r = safe_get_detailed(url)
    except (requests.exceptions.RequestException, UnsafeURLError):
        return {"is_up": False, "status_code": None, "response_time": None}
    if r["status"] >= 500:
        return {"is_up": False, "status_code": r["status"], "response_time": r["seconds"]}
    found = keyword.casefold() in r["text"].casefold()
    out = {"is_up": found, "status_code": r["status"], "response_time": r["seconds"]}
    if not found:
        out["reason"] = "keyword"
    return out


def check_keyword(url: str, keyword: str):
    result = _keyword_once(url, keyword)
    if not result["is_up"]:
        time.sleep(RETRY_DELAY)
        result = _keyword_once(url, keyword)
    return result


def in_maintenance(monitor, now=None) -> bool:
    until = getattr(monitor, "maintenance_until", None)
    return bool(until and until > (now or datetime.utcnow()))


def _port_once(host: str, port: int):
    import socket
    from app.services.safe_fetch import check_host_is_safe
    try:
        ip = check_host_is_safe(host, port)   # connect to the checked address, so DNS tricks can't redirect us
        started = time.monotonic()
        with socket.create_connection((ip, int(port)), timeout=10):
            pass
        return {"is_up": True, "status_code": None, "response_time": round(time.monotonic() - started, 3)}
    except (OSError, UnsafeURLError, ValueError):
        return {"is_up": False, "status_code": None, "response_time": None}


def check_port(host: str, port: int):
    """Is the server answering on this port? Look twice before saying it's down."""
    result = _port_once(host, port)
    if not result["is_up"]:
        time.sleep(RETRY_DELAY)
        result = _port_once(host, port)
    return result


def heartbeat_grace(minutes: int) -> int:
    """Extra time allowed before a late check-in counts as missed (jobs don't run to the second)."""
    return max(5, int(minutes * 0.1))


def check_heartbeat(monitor, now=None):
    """Up if the job checked in recently enough; None while waiting for its first check-in."""
    if not monitor.last_ping_at:
        return None
    now = now or datetime.utcnow()
    allowed = timedelta(minutes=(monitor.heartbeat_minutes or 60) + heartbeat_grace(monitor.heartbeat_minutes or 60))
    return {"is_up": now - monitor.last_ping_at <= allowed, "status_code": None, "response_time": None}


def check_any(monitor):
    """Run the right kind of check for this monitor."""
    kind = getattr(monitor, "kind", None) or "website"
    if kind == "port":
        return check_port(monitor.url, monitor.port)
    if kind == "heartbeat":
        return check_heartbeat(monitor)
    if getattr(monitor, "keyword", None):
        return check_keyword(monitor.url, monitor.keyword)
    return check_url(monitor.url)


def _due_monitors(db, now):
    """Active monitors whose plan interval has passed since their last check."""
    last = dict(
        db.query(CheckResult.monitor_id, func.max(CheckResult.checked_at))
        .group_by(CheckResult.monitor_id).all()
    )
    owners = {u.id: u for u in db.query(User).all()}
    due = []
    for m in db.query(Monitor).filter(Monitor.is_active == True).all():
        owner = owners.get(m.user_id)
        interval = timedelta(minutes=plan_for(owner)["check_minutes"])
        prev = last.get(m.id)
        # 15 s of slack so a check that ran a little late isn't skipped for a whole cycle
        if in_maintenance(m, now):
            continue            # maintenance: no checks, no alerts, no "down" marks in the history
        if prev is None or now - prev >= interval - timedelta(seconds=15):
            due.append((m, owner))
    return due


def _record(db, monitor, user, result):
    if result is None:          # a heartbeat that hasn't checked in for the first time yet
        return
    db.add(CheckResult(
        monitor_id=monitor.id,
        status_code=result["status_code"],
        response_time=result["response_time"],
        is_up=result["is_up"],
        checked_at=datetime.utcnow(),
    ))
    open_incident = db.query(Incident).filter(
        Incident.monitor_id == monitor.id, Incident.is_resolved == False
    ).first()
    wants_email = bool(user and user.email_alerts)
    email = user.email if user else None
    if not result["is_up"] and not open_incident:
        db.add(Incident(monitor_id=monitor.id))
        if wants_email:
            send_down_alert(monitor.name, monitor.url, email, tz=user.timezone, monitor=monitor, reason=result.get("reason"))
        if user and user.phone:
            send_down_sms(monitor.name, monitor.url, user.phone)
    elif result["is_up"] and open_incident:
        open_incident.is_resolved = True
        open_incident.resolved_at = datetime.utcnow()
        if wants_email:
            send_recovery_alert(monitor.name, monitor.url, email, tz=user.timezone, monitor=monitor)
        if user and user.phone:
            send_recovery_sms(monitor.name, monitor.url, user.phone)


def run_checks():
    """Runs every minute; checks only the sites that are due for their plan."""
    db = SessionLocal()
    try:
        due = _due_monitors(db, datetime.utcnow())
        if not due:
            return
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(lambda pair: check_any(pair[0]), due))
        for (monitor, user), result in zip(due, results):
            try:
                _record(db, monitor, user, result)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Failed to record check for monitor {monitor.id}: {e}")
    finally:
        db.close()
