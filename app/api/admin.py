from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt, JWTError
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Monitor, CheckResult, User, Incident, DefacementWatch, DefacementEvent, SslAlertState
import os
import hmac
from app.core.auth import SECRET_KEY, ALGORITHM
from app.core.abuse import RateLimiter, client_ip

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
templates.env.globals["site_url"] = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")

# No fallback: if ADMIN_SECRET isn't set, the admin page stays locked.
ADMIN_SECRET = os.getenv("ADMIN_SECRET")

ADMIN_COOKIE = "uptraqr_admin"
ADMIN_HOURS = 8
admin_login_limiter = RateLimiter(5, 15 * 60)   # 5 tries per connection per 15 minutes


def _is_admin(request: Request) -> bool:
    """True if the browser holds a valid admin session cookie."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not ADMIN_SECRET or not token:
        return False
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return False
    return data.get("purpose") == "admin"


def _require_admin(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": error})


@router.post("/admin/login")
def admin_login(request: Request, secret: str = Form("")):
    if not admin_login_limiter.allow(client_ip(request)):
        return RedirectResponse("/admin/login?error=slow", status_code=303)
    if not ADMIN_SECRET or not hmac.compare_digest(secret.encode(), ADMIN_SECRET.encode()):
        return RedirectResponse("/admin/login?error=wrong", status_code=303)
    token = jwt.encode({"sub": "admin", "purpose": "admin",
                        "exp": datetime.utcnow() + timedelta(hours=ADMIN_HOURS)}, SECRET_KEY, algorithm=ALGORITHM)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(ADMIN_COOKIE, token, httponly=True, secure=True, samesite="strict",
                        max_age=ADMIN_HOURS * 3600, path="/admin")
    return response


@router.post("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE, path="/admin")
    return response


@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    users = db.query(User).all()
    monitors = db.query(Monitor).all()

    user_data = []
    for user in users:
        monitor_count = db.query(Monitor).filter(Monitor.user_id == user.id).count()
        user_data.append({
            "id": user.id,
            "name": user.name,
            "status_slug": user.status_slug,
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


from app.services.cleanup import delete_monitor_rows as _delete_monitor_rows, delete_user_everything


@router.delete("/admin/monitors/{monitor_id}")
def admin_delete_monitor(monitor_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    _delete_monitor_rows(db, monitor)
    db.commit()
    return {"deleted": monitor_id}


@router.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    delete_user_everything(db, user)
    db.commit()
    return {"deleted": user_id}
