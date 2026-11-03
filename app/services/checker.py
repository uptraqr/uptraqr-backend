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
        if prev is None or now - prev >= interval - timedelta(seconds=15):
            due.append((m, owner))
    return due


def _record(db, monitor, user, result):
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
            send_down_alert(monitor.name, monitor.url, email)
        if user and user.phone:
            send_down_sms(monitor.name, monitor.url, user.phone)
    elif result["is_up"] and open_incident:
        open_incident.is_resolved = True
        open_incident.resolved_at = datetime.utcnow()
        if wants_email:
            send_recovery_alert(monitor.name, monitor.url, email)
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
            results = list(pool.map(lambda pair: check_url(pair[0].url), due))
        for (monitor, user), result in zip(due, results):
            try:
                _record(db, monitor, user, result)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Failed to record check for monitor {monitor.id}: {e}")
    finally:
        db.close()
