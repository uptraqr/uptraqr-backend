from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, Incident
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
def get_monitors(db: Session = Depends(get_db)):
    return db.query(Monitor).all()

@router.post("/monitors")
def create_monitor(monitor: MonitorCreate, db: Session = Depends(get_db)):
    new_monitor = Monitor(
        name=monitor.name,
        url=monitor.url,
        user_id=1
    )
    db.add(new_monitor)
    db.commit()
    db.refresh(new_monitor)
    return new_monitor

@router.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int, db: Session = Depends(get_db)):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    db.delete(monitor)
    db.commit()
    return {"message": "Monitor deleted"}

@router.get("/monitors/{monitor_id}/results")
def get_results(monitor_id: int, db: Session = Depends(get_db)):
    return db.query(CheckResult).filter(
        CheckResult.monitor_id == monitor_id
    ).order_by(CheckResult.checked_at.desc()).limit(50).all()

@router.get("/monitors/{monitor_id}/incidents")
def get_incidents(monitor_id: int, db: Session = Depends(get_db)):
    return db.query(Incident).filter(
        Incident.monitor_id == monitor_id
    ).order_by(Incident.started_at.desc()).all()

@router.get("/monitors/{monitor_id}/ssl")
def check_ssl_status(monitor_id: int, db: Session = Depends(get_db)):
    from app.services.ssl_checker import check_ssl
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    hostname = monitor.url.replace("https://", "").replace("http://", "").split("/")[0]
    result = check_ssl(hostname)
    return {"monitor": monitor.name, "url": monitor.url, **result}

