from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

import os
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
        last_checked = latest.checked_at.strftime("%H:%M:%S") if latest else "Never"

        if is_up == True:
            sites_up += 1
        elif is_up == False:
            sites_down += 1

        monitor_data.append({
            "id": monitor.id,
            "name": monitor.name,
            "url": monitor.url,
            "owner": owner.email if owner else "N/A",
            "is_up": is_up,
            "response_time": response_time,
            "last_checked": last_checked
        })

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "users": user_data,
        "monitors": monitor_data,
        "total_users": len(users),
        "total_monitors": len(monitors),
        "sites_up": sites_up,
        "sites_down": sites_down
    })