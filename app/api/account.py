"""Account settings (password, email choices, billing, delete) and one-click unsubscribe."""
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.abuse import RateLimiter, client_ip
from app.core.auth import get_current_user_optional, hash_password, verify_password, read_link_token
from app.core.database import get_db
from app.core.plans import plan_for, plan_key
from app.models.models import User, Monitor
from app.core.timefmt import TZ_CHOICES, clean_tz, tz_label
from app.core.plans import trial_days_left
from app.services.trials import can_start_trial, start_trial

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
templates.env.globals["site_url"] = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")

password_limiter = RateLimiter(10, 60 * 60)   # wrong current-password guesses per account per hour

MESSAGES = {
    "password": ("ok", "Your password is saved. You can now log in with it."),
    "prefs": ("ok", "Your email choices are saved."),
    "trial": ("ok", "Your 14-day Pro trial has started. Every feature is switched on."),
    "notrial": ("error", "A free trial has already been used for this email address."),
    "tz": ("ok", "Your time zone is saved. Alerts and your dashboard now use it."),
    "short": ("error", "Your new password needs at least 8 characters."),
    "mismatch": ("error", "The two new passwords don't match. Please type them again."),
    "wrong": ("error", "Your current password isn't right. If you've forgotten it, log out and use 'Email me a login link'."),
    "slow": ("error", "Too many tries. Please wait an hour and try again."),
    "confirm": ("error", "To delete your account, type DELETE in capital letters."),
    "paid": ("error", "Please cancel your paid plan first (Manage billing), then delete your account."),
}


def _need_login(request, db):
    user = get_current_user_optional(request, db)
    return user, (None if user else RedirectResponse("/login", status_code=303))


def _back(code):
    return RedirectResponse(f"/account?msg={code}", status_code=303)


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    return templates.TemplateResponse("account.html", {
        "request": request, "user": user,
        "plan": plan_for(user), "plan_key": plan_key(user),
        "site_count": db.query(Monitor).filter(Monitor.user_id == user.id).count(),
        "message": MESSAGES.get(msg),
        "tz_choices": TZ_CHOICES, "tz_label": tz_label(user.timezone),
        "trial_days": trial_days_left(user), "trial_available": can_start_trial(db, user),
    })


@router.post("/account/password")
def set_password(request: Request, new_password: str = Form(...), confirm_password: str = Form(...),
                 current_password: str = Form(""), db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    if user.password_set:
        # Someone who already has a password must prove they know it before changing it.
        if not password_limiter.allow(f"pw:{user.id}"):
            return _back("slow")
        if not verify_password(current_password, user.password):
            return _back("wrong")
    if len(new_password) < 8:
        return _back("short")
    if len(new_password) > 128:
        new_password = new_password[:128]
    if new_password != confirm_password[:128]:
        return _back("mismatch")
    user.password = hash_password(new_password)
    user.password_set = True
    db.commit()
    return _back("password")


@router.post("/account/emails")
def save_email_choices(request: Request, email_alerts: str = Form(""), monthly_reports: str = Form(""),
                       db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    user.email_alerts = email_alerts == "on"
    user.monthly_reports = monthly_reports == "on"
    db.commit()
    return _back("prefs")


@router.post("/account/trial")
def begin_trial(request: Request, db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    if not user.email_verified or not start_trial(db, user):
        return _back("notrial")
    db.commit()
    return RedirectResponse("/dashboard?note=trial", status_code=303)


@router.post("/account/timezone")
def save_timezone(request: Request, tz: str = Form(""), db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    user.timezone = clean_tz(tz)
    db.commit()
    return _back("tz")


@router.post("/account/delete")
def delete_account(request: Request, confirm: str = Form(""), db: Session = Depends(get_db)):
    user, go = _need_login(request, db)
    if go:
        return go
    if confirm.strip() != "DELETE":
        return _back("confirm")
    if user.stripe_subscription_id and plan_key(user) != "free":
        return _back("paid")
    from app.services.cleanup import delete_user_everything
    delete_user_everything(db, user)
    db.commit()
    response = RedirectResponse("/?deleted=1", status_code=303)
    response.delete_cookie("access_token")
    return response


# ---- Unsubscribe (works from the email without logging in) -------------------------

KINDS = {"alerts": ("email_alerts", "website alert emails"), "reports": ("monthly_reports", "monthly report emails")}
unsubscribe_limiter = RateLimiter(30, 60 * 60)


def _unsub_user(token, db):
    data = read_link_token(token or "", "unsubscribe")
    if not data or data.get("kind") not in KINDS:
        return None, None
    return db.query(User).filter(User.email == data["sub"]).first(), data["kind"]


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    # Showing a button (not unsubscribing straight away) stops email scanners that open links from turning emails off.
    user, kind = _unsub_user(token, db)
    return templates.TemplateResponse("unsubscribe.html", {
        "request": request, "valid": bool(user), "token": token, "done": False,
        "what": KINDS[kind][1] if kind else "", "email": user.email if user else "",
    }, status_code=200 if user else 400)


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(request: Request, token: str = "", form_token: str = Form("", alias="token"),
                db: Session = Depends(get_db)):
    # Gmail and Outlook's own "Unsubscribe" button posts here with the token in the link (one-click unsubscribe).
    if not unsubscribe_limiter.allow(client_ip(request)):
        return HTMLResponse("Too many requests. Please try again later.", status_code=429)
    user, kind = _unsub_user(form_token or token, db)
    if user:
        setattr(user, KINDS[kind][0], False)
        db.commit()
    return templates.TemplateResponse("unsubscribe.html", {
        "request": request, "valid": bool(user), "done": bool(user), "token": "",
        "what": KINDS[kind][1] if kind else "", "email": user.email if user else "",
    }, status_code=200 if user else 400)
