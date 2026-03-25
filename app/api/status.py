from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, User
from datetime import datetime

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/status/{username}", response_class=HTMLResponse)
def public_status(username: str, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Status page not found")

    monitors = db.query(Monitor).filter(
        Monitor.user_id == user.id,
        Monitor.is_active == True
    ).all()

    monitor_data = []
    all_up = True

    for monitor in monitors:
        latest = db.query(CheckResult).filter(
            CheckResult.monitor_id == monitor.id
        ).order_by(CheckResult.checked_at.desc()).first()

        is_up = latest.is_up if latest else None
        response_time = round(latest.response_time, 2) if latest and latest.response_time else "N/A"

        total = db.query(CheckResult).filter(
            CheckResult.monitor_id == monitor.id
        ).count()
        up_count = db.query(CheckResult).filter(
            CheckResult.monitor_id == monitor.id,
            CheckResult.is_up == True
        ).count()
        uptime = round((up_count / total * 100), 2) if total > 0 else 100.0

        if is_up == False:
            all_up = False

        monitor_data.append({
            "name": monitor.name,
            "url": monitor.url,
            "is_up": is_up,
            "response_time": response_time,
            "uptime": uptime
        })

    return templates.TemplateResponse("status.html", {
        "request": request,
        "user_name": user.name,
        "monitors": monitor_data,
        "all_up": all_up,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    })