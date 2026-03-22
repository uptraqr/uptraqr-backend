from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult
from app.services.ssl_checker import check_ssl

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
    monitor_data = []
    sites_up = 0
    sites_down = 0
    ssl_warnings = 0

    for monitor in monitors:
        latest = db.query(CheckResult).filter(
            CheckResult.monitor_id == monitor.id
        ).order_by(CheckResult.checked_at.desc()).first()

        is_up = latest.is_up if latest else None
        response_time = round(latest.response_time, 2) if latest and latest.response_time else "N/A"
        last_checked = latest.checked_at.strftime("%H:%M:%S") if latest else "Never"

        ssl = check_ssl(monitor.url.replace("https://", "").replace("http://", "").split("/")[0])
        ssl_days = ssl["days_left"] if ssl["valid"] else "N/A"
        ssl_warning = ssl.get("expiring_soon", False)

        if is_up:
            sites_up += 1
        else:
            sites_down += 1

        if ssl_warning:
            ssl_warnings += 1

        monitor_data.append({
            "name": monitor.name,
            "url": monitor.url,
            "is_up": is_up,
            "response_time": response_time,
            "ssl_days": ssl_days,
            "ssl_warning": ssl_warning,
            "last_checked": last_checked
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "monitors": monitor_data,
        "total_monitors": len(monitors),
        "sites_up": sites_up,
        "sites_down": sites_down,
        "ssl_warnings": ssl_warnings
    })