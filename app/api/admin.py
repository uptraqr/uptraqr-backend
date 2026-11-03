from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, User, Incident, DefacementWatch, DefacementEvent
import os
import hmac

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")

# No fallback: if ADMIN_SECRET isn't set, the admin page stays locked.
ADMIN_SECRET = os.getenv("ADMIN_SECRET")

def _check_secret(secret: str):
    if not ADMIN_SECRET or not hmac.compare_digest(secret.encode(), ADMIN_SECRET.encode()):
        raise HTTPException(status_code=403, detail="Access denied")

@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, secret: str = "", db: Session = Depends(get_db)):
    _check_secret(secret)

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
        last_checked = latest.checked_at.strftime("%Y-%m-%d %H:%M") if latest and latest.checked_at else "Never"

        if is_up is True:
            sites_up += 1
        elif is_up is False:
            sites_down += 1

        monitor_data.append({
            "id": monitor.id,
            "name": monitor.name,
            "url": monitor.url,
            "owner": owner.email if owner else "N/A",
            "is_up": is_up,
            "response_time": response_time,
            "last_checked": last_checked,
        })

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "users": user_data,
        "monitors": monitor_data,
        "total_users": len(user_data),
        "total_monitors": len(monitor_data),
        "sites_up": sites_up,
        "sites_down": sites_down,
    })


def _delete_monitor_rows(db: Session, monitor: Monitor):
    db.query(CheckResult).filter(CheckResult.monitor_id == monitor.id).delete()
    db.query(Incident).filter(Incident.monitor_id == monitor.id).delete()
    db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).delete()
    db.query(DefacementEvent).filter(DefacementEvent.monitor_id == monitor.id).delete()
    db.delete(monitor)


@router.delete("/admin/monitors/{monitor_id}")
def admin_delete_monitor(monitor_id: int, secret: str = "", db: Session = Depends(get_db)):
    _check_secret(secret)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    _delete_monitor_rows(db, monitor)
    db.commit()
    return {"deleted": monitor_id}


@router.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, secret: str = "", db: Session = Depends(get_db)):
    _check_secret(secret)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for monitor in db.query(Monitor).filter(Monitor.user_id == user.id).all():
        _delete_monitor_rows(db, monitor)
    db.delete(user)
    db.commit()
    return {"deleted": user_id}
