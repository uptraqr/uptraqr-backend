import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import get_current_user_optional
from app.models.models import Monitor, CheckResult, User, DefacementWatch
import json
from app.core.plans import plan_for
from app.services.history import uptime_percent
from app.services.ssl_checker import check_ssl

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
templates.env.globals["site_url"] = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_optional(request, db)

    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    if not current_user.email_verified:
        response = templates.TemplateResponse("verify_email.html", {"request": request, "state": "pending", "user": current_user})
        response.headers["Cache-Control"] = "no-store"
        return response

    monitors = db.query(Monitor).filter(
        Monitor.user_id == current_user.id,
        Monitor.is_active == True
    ).all()

    plan = plan_for(current_user)
    monitor_data = []
    sites_up = 0
    sites_down = 0
    ssl_warnings = 0
    tamper_alerts = 0

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

        if is_up == True:
            sites_up += 1
        elif is_up == False:
            sites_down += 1

        if ssl_warning:
            ssl_warnings += 1

        watch = db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).first()
        tamper_status = "paused" if (watch and not watch.enabled) else (watch.status if watch else "learning")
        if plan["tamper_minutes"] is None:
            tamper_status = "locked"
        if tamper_status in ("changed", "suspicious"):
            tamper_alerts += 1

        monitor_data.append({
            "id": monitor.id,
            "name": monitor.name,
            "url": monitor.url,
            "is_up": is_up,
            "response_time": response_time,
            "ssl_days": ssl_days,
            "ssl_warning": ssl_warning,
            "last_checked": last_checked,
            "tamper_status": tamper_status,
            "uptime_30": uptime_percent(db, monitor.id, 30) if plan["history_days"] else None,
            "tamper_checked": watch.last_checked_at.strftime("%Y-%m-%dT%H:%M:%SZ") if watch and watch.last_checked_at else None,
        })

    # Problems first: down sites, then possible hacks, then changes, then expiring SSL.
    def urgency(m):
        if m["is_up"] is False: return 0
        if m["tamper_status"] == "suspicious": return 1
        if m["tamper_status"] == "changed": return 2
        if m["ssl_warning"]: return 3
        return 4
    monitor_data.sort(key=urgency)
    needs_attention = sum(1 for m in monitor_data if urgency(m) < 4)
    response = templates.TemplateResponse("dashboard.html", {
        "needs_attention": needs_attention,
        "request": request,
        "monitors": monitor_data,
        "total_monitors": len(monitors),
        "sites_up": sites_up,
        "sites_down": sites_down,
        "ssl_warnings": ssl_warnings,
        "tamper_alerts": tamper_alerts,
        "user": current_user,
        "plan": plan
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response