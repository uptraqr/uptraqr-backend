from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import Monitor, CheckResult, Incident, User
from pydantic import BaseModel
from typing import Optional
import json
from app.models.models import DefacementWatch, DefacementEvent, SslAlertState
from app.services.safe_fetch import check_url_is_safe, UnsafeURLError
from app.core.plans import plan_for

router = APIRouter()

from app.core.abuse import RateLimiter
# "Check now" style buttons make real requests to the website, so they're limited per account.
live_check_limiter = RateLimiter(limit=10, window=60)


def _limit_live_checks(user):
    if not live_check_limiter.allow(f"u:{user.id}"):
        raise HTTPException(status_code=429, detail="That's a lot of checks in a short time. Please wait a minute and try again.")

class MonitorCreate(BaseModel):
    name: str
    url: str = ""
    kind: str = "website"            # website | port | heartbeat
    port: Optional[int] = None
    every_minutes: Optional[int] = None
    keyword: Optional[str] = None


class MonitorSettings(BaseModel):
    keyword: Optional[str] = None


class Maintenance(BaseModel):
    minutes: int          # 0 ends maintenance now

MAINTENANCE_CHOICES = {0, 30, 60, 240, 1440}


def _clean_keyword(k):
    k = (k or "").strip()
    if len(k) > 100:
        raise HTTPException(status_code=400, detail="Keep the words to check under 100 characters.")
    return k or None

HEARTBEAT_CHOICES = {5, 15, 30, 60, 360, 720, 1440, 10080}   # 5 min ... 1 week

class MonitorUpdate(BaseModel):
    name: Optional[str]
    url: Optional[str]
    is_active: Optional[bool]

@router.get("/monitors")
def get_monitors(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Monitor).filter(Monitor.user_id == current_user.id).all()

def add_monitor_for(db, user, raw_url: str, name: str) -> Monitor:
    """Shared rules for adding a website (used by the dashboard and the email sign-up link)."""
    from app.core.abuse import site_key
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please confirm your email address first. Check your inbox for our link.")
    plan = plan_for(user)
    url = (raw_url or "").strip()
    if not url or len(url) > 2000:
        raise HTTPException(status_code=400, detail="Please enter a website address, like yourbusiness.ca")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        check_url_is_safe(url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    key = site_key(url)
    mine = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.is_active == True).all()
    if any((m.kind or "website") == "website" and site_key(m.url) == key for m in mine):
        raise HTTPException(status_code=409, detail="You're already watching this website.")
    if sum(1 for m in mine if (m.kind or "website") == "website") >= plan["sites"]:
        raise HTTPException(
            status_code=403,
            detail=f"Your {plan['label']} plan includes {plan['sites']} website{'s' if plan['sites'] != 1 else ''}. Upgrade your plan to add more."
        )
    if plan["label"] == "Free":
        free_owner_ids = [u.id for u in db.query(User).all() if plan_for(u)["label"] == "Free" and u.id != user.id]
        if free_owner_ids:
            for (other_url,) in db.query(Monitor.url).filter(Monitor.user_id.in_(free_owner_ids), Monitor.kind == "website").all():
                if site_key(other_url) == key:
                    raise HTTPException(status_code=409, detail="This website is already being watched on another free account. Upgrade to a paid plan to watch it here too.")
    name = (name or "").strip()[:100] or key
    new_monitor = Monitor(name=name, url=url, user_id=user.id)
    db.add(new_monitor)
    db.commit()
    db.refresh(new_monitor)
    return new_monitor


def add_server_monitor(db, user, data: MonitorCreate) -> Monitor:
    """Port checks and scheduled-job (heartbeat) checks: paid plans only."""
    import secrets
    from app.services.safe_fetch import check_host_is_safe
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please confirm your email address first. Check your inbox for our link.")
    plan = plan_for(user)
    if not plan["servers"]:
        raise HTTPException(status_code=403, detail="Server and scheduled job checks are included on paid plans. Upgrade to Starter or above to add one.")
    from app.core.plans import limit_for, KIND_WORDS
    if data.kind in ("port", "heartbeat"):
        used = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.is_active == True, Monitor.kind == data.kind).count()
        cap = limit_for(plan, data.kind)
        if used >= cap:
            one, many = KIND_WORDS[data.kind]
            raise HTTPException(status_code=403, detail=f"Your {plan['label']} plan includes {cap} {one if cap == 1 else many}. Upgrade your plan to add more.")
    name = data.name.strip()[:100]
    if data.kind == "port":
        host = (data.url or "").strip().lower()
        for prefix in ("https://", "http://", "tcp://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        host = host.split("/")[0]
        if ":" in host and host.count(":") == 1 and data.port is None:
            host, _, p = host.partition(":")
            data.port = int(p) if p.isdigit() else None
        if not data.port:
            raise HTTPException(status_code=400, detail="Please enter the port number, for example 587 for an email server.")
        try:
            check_host_is_safe(host, data.port)
        except (UnsafeURLError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        dup = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.kind == "port",
                                       Monitor.url == host, Monitor.port == data.port).first()
        if dup:
            raise HTTPException(status_code=409, detail="You're already watching that server and port.")
        m = Monitor(user_id=user.id, name=name, url=host, kind="port", port=int(data.port))
    elif data.kind == "heartbeat":
        if data.every_minutes not in HEARTBEAT_CHOICES:
            raise HTTPException(status_code=400, detail="Please choose how often this job runs.")
        m = Monitor(user_id=user.id, name=name, url="heartbeat", kind="heartbeat",
                    heartbeat_minutes=data.every_minutes, heartbeat_token=secrets.token_urlsafe(18))
    else:
        raise HTTPException(status_code=400, detail="Unknown check type.")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.post("/monitors")
def create_monitor(monitor: MonitorCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not monitor.name.strip():
        raise HTTPException(status_code=400, detail="Please give this a name.")
    if monitor.kind in ("port", "heartbeat"):
        return add_server_monitor(db, current_user, monitor)
    keyword = _clean_keyword(monitor.keyword)
    m = add_monitor_for(db, current_user, monitor.url, monitor.name)
    if keyword:
        m.keyword = keyword
        db.commit()
        db.refresh(m)
    return m


@router.post("/monitors/{monitor_id}/settings")
def update_settings(monitor_id: int, data: MonitorSettings, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = _own_monitor(db, monitor_id, current_user)
    if (monitor.kind or "website") != "website":
        raise HTTPException(status_code=400, detail="Keyword checks are for websites.")
    monitor.keyword = _clean_keyword(data.keyword)
    db.commit()
    return {"keyword": monitor.keyword}


@router.post("/monitors/{monitor_id}/maintenance")
def set_maintenance(monitor_id: int, data: Maintenance, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Pause checks and alerts while the owner works on the site. Ends by itself."""
    from datetime import datetime, timedelta
    if data.minutes not in MAINTENANCE_CHOICES:
        raise HTTPException(status_code=400, detail="Choose how long to pause alerts.")
    monitor = _own_monitor(db, monitor_id, current_user)
    if data.minutes == 0:
        monitor.maintenance_until = None
    else:
        monitor.maintenance_until = datetime.utcnow() + timedelta(minutes=data.minutes)
        if (monitor.kind or "website") == "website":
            monitor.relearn_after_maintenance = True    # their changes become the new normal for tamper watch
    db.commit()
    return {"maintenance_until": monitor.maintenance_until.strftime("%Y-%m-%dT%H:%M:%SZ") if monitor.maintenance_until else None}

@router.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    from app.services.cleanup import delete_monitor_rows
    delete_monitor_rows(db, monitor)
    db.commit()
    return {"message": "Monitor deleted"}

@router.get("/monitors/{monitor_id}/results")
def get_results(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return db.query(CheckResult).filter(
        CheckResult.monitor_id == monitor_id
    ).order_by(CheckResult.checked_at.desc()).limit(50).all()

@router.get("/monitors/{monitor_id}/incidents")
def get_incidents(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return db.query(Incident).filter(
        Incident.monitor_id == monitor_id
    ).order_by(Incident.started_at.desc()).all()

@router.get("/monitors/{monitor_id}/ssl")
def check_ssl_status(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.ssl_checker import check_ssl
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    _limit_live_checks(current_user)
    hostname = monitor.url.replace("https://", "").replace("http://", "").split("/")[0]
    result = check_ssl(hostname)
    return {"monitor": monitor.name, "url": monitor.url, **result}

@router.post("/monitors/{monitor_id}/check")
def check_now(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.checker import check_any
    from app.models.models import CheckResult
    from datetime import datetime
    
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    _limit_live_checks(current_user)
    result = check_any(monitor)
    if result is None:
        return {"status": "waiting", "is_up": None, "response_time": None}
    check = CheckResult(
        monitor_id=monitor.id,
        status_code=result["status_code"],
        response_time=result["response_time"],
        is_up=result["is_up"],
        checked_at=datetime.utcnow()
    )
    db.add(check)
    db.commit()
    return {"status": "checked", "is_up": result["is_up"], "response_time": result["response_time"]}


# ---------------- Defacement monitoring ----------------

def _require_tamper(user):
    if plan_for(user)["tamper_minutes"] is None:
        raise HTTPException(status_code=403, detail="Tamper watch is included on paid plans. Upgrade to Starter or above to turn it on.")


def _own_monitor(db, monitor_id, user):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


def _watch_view(db, monitor, watch):
    events = db.query(DefacementEvent).filter(DefacementEvent.monitor_id == monitor.id) \
        .order_by(DefacementEvent.detected_at.desc()).limit(10).all()
    return {
        "monitor_id": monitor.id,
        "enabled": watch.enabled if watch else True,
        "status": watch.status if watch else "learning",
        "baseline_set_at": watch.baseline_set_at.isoformat() + "Z" if watch and watch.baseline_set_at else None,
        "last_checked_at": watch.last_checked_at.isoformat() + "Z" if watch and watch.last_checked_at else None,
        "last_error": watch.last_error if watch else None,
        "findings": json.loads(watch.last_findings) if watch and watch.last_findings else [],
        "history": [{
            "detected_at": e.detected_at.isoformat() + "Z",
            "status": e.status,
            "resolution": e.resolution,
            "findings": json.loads(e.findings or "[]"),
        } for e in events],
    }


class DefacementToggle(BaseModel):
    enabled: bool


@router.get("/monitors/{monitor_id}/defacement")
def defacement_status(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = _own_monitor(db, monitor_id, current_user)
    watch = db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).first()
    return _watch_view(db, monitor, watch)


@router.post("/monitors/{monitor_id}/defacement/scan")
def defacement_scan_now(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.defacement_runner import check_monitor
    from datetime import datetime, timedelta
    _require_tamper(current_user)
    monitor = _own_monitor(db, monitor_id, current_user)
    existing = db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).first()
    # Small cooldown so the button can't be used to hammer a website.
    if existing and existing.last_checked_at and datetime.utcnow() - existing.last_checked_at < timedelta(seconds=60):
        return _watch_view(db, monitor, existing)
    watch = check_monitor(db, monitor)
    db.commit()
    return _watch_view(db, monitor, watch)


@router.post("/monitors/{monitor_id}/defacement/approve")
def defacement_approve(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """'Yes, I made this change' — the current page becomes the new known-good version."""
    from app.services.defacement_runner import get_or_create_watch, learn, resolve_open_events
    import requests as _rq
    _require_tamper(current_user)
    monitor = _own_monitor(db, monitor_id, current_user)
    watch = get_or_create_watch(db, monitor)
    try:
        learn(db, monitor, watch)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except _rq.RequestException:
        raise HTTPException(status_code=502, detail="We couldn't load your page right now. Try again in a minute.")
    resolve_open_events(db, monitor.id, "approved")
    db.commit()
    return _watch_view(db, monitor, watch)


@router.post("/monitors/{monitor_id}/defacement/toggle")
def defacement_toggle(monitor_id: int, data: DefacementToggle, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.defacement_runner import get_or_create_watch
    _require_tamper(current_user)
    monitor = _own_monitor(db, monitor_id, current_user)
    watch = get_or_create_watch(db, monitor)
    watch.enabled = data.enabled
    db.commit()
    return _watch_view(db, monitor, watch)



@router.get("/monitors/{monitor_id}/history")
def monitor_history(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from datetime import datetime, timedelta
    from app.services.history import uptime_percent, daily_bars
    plan = plan_for(current_user)
    if not plan["history_days"]:
        raise HTTPException(status_code=403, detail="History is included on paid plans. Upgrade to see uptime and outages over time.")
    monitor = _own_monitor(db, monitor_id, current_user)
    keep = plan["history_days"]
    since = datetime.utcnow() - timedelta(days=keep)
    outages = db.query(Incident).filter(Incident.monitor_id == monitor.id, Incident.started_at >= since) \
        .order_by(Incident.started_at.desc()).limit(50).all()
    return {
        "history_days": keep,
        "uptime": {str(d): uptime_percent(db, monitor.id, d) for d in (7, 30, 90, 365) if d <= keep},
        "bars": daily_bars(db, monitor.id, min(keep, 30)),
        "outages": [{
            "started_at": o.started_at.isoformat() + "Z",
            "resolved_at": o.resolved_at.isoformat() + "Z" if o.resolved_at else None,
            "minutes": round(((o.resolved_at or datetime.utcnow()) - o.started_at).total_seconds() / 60),
        } for o in outages],
    }
