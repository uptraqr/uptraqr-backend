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

router = APIRouter()

class MonitorCreate(BaseModel):
    name: str
    url: str

class MonitorUpdate(BaseModel):
    name: Optional[str]
    url: Optional[str]
    is_active: Optional[bool]

@router.get("/monitors")
def get_monitors(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Monitor).filter(Monitor.user_id == current_user.id).all()

@router.post("/monitors")
def create_monitor(monitor: MonitorCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    
    # Check plan limits
    monitor_count = db.query(Monitor).filter(
        Monitor.user_id == current_user.id,
        Monitor.is_active == True
    ).count()

    limits = {
        None: 1,        # Free — 1 monitor trial
        "starter": 3,
        "pro": 10,
        "agency": 999
    }

    limit = limits.get(current_user.plan, 1)

    if monitor_count >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"You've reached your plan limit of {limit} monitors. Please upgrade your plan."
        )

    url = monitor.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        check_url_is_safe(url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    name = monitor.name.strip()[:100]
    if not name:
        raise HTTPException(status_code=400, detail="Please give this website a name.")

    new_monitor = Monitor(
        name=name,
        url=url,
        user_id=current_user.id
    )
    db.add(new_monitor)
    db.commit()
    db.refresh(new_monitor)
    return new_monitor

@router.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).delete()
    db.query(DefacementEvent).filter(DefacementEvent.monitor_id == monitor.id).delete()
    db.query(SslAlertState).filter(SslAlertState.monitor_id == monitor.id).delete()
    db.delete(monitor)
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
    hostname = monitor.url.replace("https://", "").replace("http://", "").split("/")[0]
    result = check_ssl(hostname)
    return {"monitor": monitor.name, "url": monitor.url, **result}

@router.post("/monitors/{monitor_id}/check")
def check_now(monitor_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.checker import check_url
    from app.models.models import CheckResult
    from datetime import datetime
    
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id
    ).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    result = check_url(monitor.url)
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
    monitor = _own_monitor(db, monitor_id, current_user)
    watch = get_or_create_watch(db, monitor)
    watch.enabled = data.enabled
    db.commit()
    return _watch_view(db, monitor, watch)
