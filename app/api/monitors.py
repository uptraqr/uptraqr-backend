from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import Monitor, CheckResult, Incident, User
from pydantic import BaseModel
from typing import Optional

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

    new_monitor = Monitor(
        name=monitor.name,
        url=monitor.url,
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