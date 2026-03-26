from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, User
import os

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "fallback-secret")

@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, secret: str = "", db: Session = Depends(get_db)):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Access denied")

    users = db.query(User).all()
    monitors = db.query(Monitor).all()

    user_data = []
    for user in users:
        monitor_count = db.query(Monitor).filter(Monitor.user_id == user.id).count()
        user_data.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "monitor_count": monitor_count,
            "created_at": user.created_at.strftime("%Y-%m-%d") if user.created_at else "N/A"
        })

    monitor_data = []
    sites_up = 0
    sites_down = 0

    for monitor in monitors:
        owner = db.query(User).filter(User.id == monitor.user_id).first()
        latest = db.query(CheckResult).filter(
            CheckResult.monitor_id == monitor.id
        ).order_by(CheckResult.checked_at.desc()).first()

        is_up = latest.is_up if latest else None
        response_time = round(latest.response_time, 2) if latest and latest.response_time else "N/A"
        last_checked = latest.checked_at.strftim