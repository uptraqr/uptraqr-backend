import os
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import hash_password, verify_password, create_access_token, create_verify_token, read_verify_token
from app.services.email_alerts import send_verification_email, send_report_email, send_login_link_email
from app.core.auth import create_link_token, read_link_token
from app.core.abuse import RateLimiter
from urllib.parse import quote
import secrets as _secrets
import re as _re
import time
from app.core.abuse import canonical_email, is_disposable, client_ip, signup_limiter
from app.models.models import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
templates.env.globals["site_url"] = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
SITE_URL = templates.env.globals["site_url"]
# Safety switch: set REQUIRE_EMAIL_VERIFICATION=false in Railway if emails ever stop sending,
# so new customers aren't locked out while you fix it.
REQUIRE_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "true").lower() != "false"
_last_sent = {}   # user id -> time of last confirmation email (simple resend limit)
RESEND_WAIT = 60  # seconds


def _send_confirmation(user) -> bool:
    _last_sent[user.id] = time.time()
    link = f"{SITE_URL}/verify-email?token={create_verify_token(user.email)}"
    return send_verification_email(user.email, user.name, link)


def _login_response(user, url="/dashboard"):
    token = create_access_token({"sub": user.email})
    response = RedirectResponse(url=url, status_code=303)
    response.set_cookie(key="access_token", value=token, httponly=True, secure=True, samesite="Lax", max_age=60*60*24)
    return response

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@router.post("/api/auth/signup")
def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    email = email.strip()
    if len(password) < 8:
        return RedirectResponse(url="/signup?error=short", status_code=303)
    if is_disposable(email):
        return RedirectResponse(url="/signup?error=disposable", status_code=303)
    canon = canonical_email(email)
    existing = db.query(User).filter((User.email == email) | (User.email_canonical == canon)).first()
    if existing:
        return RedirectResponse(url="/signup?error=exists", status_code=303)
    if not signup_limiter.allow(client_ip(request)):
        return RedirectResponse(url="/signup?error=limit", status_code=303)
    new_user = User(
        email=email,
        password=hash_password(password),
        name=name.strip()[:100],
        email_verified=not REQUIRE_VERIFICATION,
        email_canonical=canon,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    if REQUIRE_VERIFICATION:
        _send_confirmation(new_user)
    return _login_response(new_user)

@router.post("/api/auth/login")
def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email.strip()).first()
    if not user or not verify_password(password, user.password):
        return RedirectResponse(url="/login?error=invalid", status_code=303)
    return _login_response(user)

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

class UpdatePhone(BaseModel):
    phone: str

@router.post("/api/auth/update-phone")
def update_phone(
    data: UpdatePhone,
    request: Request,
    db: Session = Depends(get_db)
):
    from app.core.auth import get_current_user_optional
    current_user = get_current_user_optional(request, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import re
    phone = data.phone.strip()
    if not re.fullmatch(r"\+?[0-9 ()\-.]{7,20}", phone):
        raise HTTPException(status_code=400, detail="That doesn't look like a phone number. Use a format like +1 604 555 0123.")
    current_user.phone = phone
    db.commit()
    return {"message": "Phone updated successfully"}



@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str = "", db: Session = Depends(get_db)):
    email = read_verify_token(token)
    user = db.query(User).filter(User.email == email).first() if email else None
    if not user:
        return templates.TemplateResponse("verify_email.html", {"request": request, "state": "invalid"}, status_code=400)
    if not user.email_verified:
        user.email_verified = True
        db.commit()
    return templates.TemplateResponse("verify_email.html", {"request": request, "state": "done"})


@router.post("/api/auth/resend-verification")
def resend_verification(request: Request, db: Session = Depends(get_db)):
    from app.core.auth import get_current_user_optional
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in first.")
    if user.email_verified:
        return {"message": "Your email is already confirmed."}
    wait = RESEND_WAIT - (time.time() - _last_sent.get(user.id, 0))
    if wait > 0:
        raise HTTPException(status_code=429, detail=f"Please wait {int(wait) + 1} seconds before asking for another email.")
    if not _send_confirmation(user):
        raise HTTPException(status_code=502, detail="We couldn't send the email right now. Try again in a few minutes.")
    return {"message": f"Sent. Check {user.email}, including your spam folder."}



# ---------------- Email-only start (from the website health report) ----------------
quickstart_ip_limiter = RateLimiter(limit=5, window=3600)       # report emails per connection per hour
email_send_limiter = RateLimiter(limit=3, window=3600)          # emails per inbox per hour (any kind)
EMAIL_RE = _re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[a-zA-Z]{2,}$")


def _inbox_page(request, email=None, error=None, status_code=200):
    return templates.TemplateResponse("inbox.html", {"request": request, "email": email, "error": error}, status_code=status_code)


@router.post("/api/quickstart", response_class=HTMLResponse)
def quickstart(request: Request, email: str = Form(...), url: str = Form(...), db: Session = Depends(get_db)):
    """Email the health report; the email's button creates a free account (or logs in) and adds the site."""
    from app.api.report import get_report
    from app.services.report import normalise_url
    from app.services.safe_fetch import UnsafeURLError
    email = email.strip()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return _inbox_page(request, error="That email address doesn't look right. Please check it and try again.", status_code=400)
    if is_disposable(email):
        return _inbox_page(request, error="Temporary email addresses can't be used. Please use an email you check, since that's where your alerts go.", status_code=400)
    canon = canonical_email(email)
    ip = client_ip(request)
    if not quickstart_ip_limiter.allow(ip) or not email_send_limiter.allow(canon):
        return _inbox_page(request, error="Too many requests. Please wait a few minutes and try again.", status_code=429)
    try:
        site = normalise_url(url)
        report = get_report(site)
    except (UnsafeURLError, Exception) as e:
        return _inbox_page(request, error="We couldn't check that website again just now. Please run the check again.", status_code=400)

    user = db.query(User).filter((User.email == email) | (User.email_canonical == canon)).first()
    new_account = user is None
    if new_account:
        if not signup_limiter.allow(ip):
            return _inbox_page(request, error="Too many accounts have been created from your connection today. Try again tomorrow.", status_code=429)
        user = User(
            email=email,
            # No password yet: they log in with emailed links, and can set one later.
            password=hash_password(_secrets.token_urlsafe(32)),
            name=email.split("@")[0][:100],
            email_verified=False,
            email_canonical=canon,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_link_token(user.email, "quickstart", 24 * 60, url=site)
    action_link = f"{SITE_URL}/start?token={token}"
    report_link = f"{SITE_URL}/check?url={quote(report['host'])}"
    if not send_report_email(user.email, report, action_link, report_link, new_account):
        return _inbox_page(request, error="We couldn't send the email right now. Please try again in a few minutes.", status_code=502)
    # Same page whether or not the email already had an account, so nobody can use this to find out who's signed up.
    return _inbox_page(request, email=email)


@router.get("/start")
def quickstart_confirm(request: Request, token: str = "", db: Session = Depends(get_db)):
    """The button in the report email: confirms the email, logs in, and adds the website."""
    from app.api.monitors import add_monitor_for
    data = read_link_token(token, "quickstart")
    user = db.query(User).filter(User.email == data["sub"]).first() if data else None
    if not user:
        return templates.TemplateResponse("verify_email.html", {"request": request, "state": "invalid"}, status_code=400)
    if not user.email_verified:
        user.email_verified = True
        db.commit()
    note = "added"
    try:
        add_monitor_for(db, user, data.get("url", ""), "")
    except HTTPException as e:
        note = "exists" if e.status_code == 409 and "already watching" in str(e.detail) else ("taken" if e.status_code == 409 else "limit")
    return _login_response(user, url=f"/dashboard?note={note}")


# ---------------- Passwordless login links ----------------
@router.post("/api/auth/login-link")
def request_login_link(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip()
    canon = canonical_email(email)
    if EMAIL_RE.match(email) and quickstart_ip_limiter.allow(client_ip(request)) and email_send_limiter.allow(canon):
        user = db.query(User).filter((User.email == email) | (User.email_canonical == canon)).first()
        if user:
            link = f"{SITE_URL}/login-link?token={create_link_token(user.email, 'login', 30)}"
            send_login_link_email(user.email, link)
    # Always the same answer, so this can't be used to check who has an account.
    return RedirectResponse(url="/login?sent=1", status_code=303)


@router.get("/login-link")
def use_login_link(request: Request, token: str = "", db: Session = Depends(get_db)):
    data = read_link_token(token, "login")
    user = db.query(User).filter(User.email == data["sub"]).first() if data else None
    if not user:
        return templates.TemplateResponse("verify_email.html", {"request": request, "state": "invalid"}, status_code=400)
    if not user.email_verified:
        user.email_verified = True   # they proved they own the inbox
        db.commit()
    return _login_response(user)
