import os
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import hash_password, verify_password, create_access_token, create_verify_token, read_verify_token
from app.services.email_alerts import send_verification_email
import time
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
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    email = email.strip()
    if len(password) < 8:
        return RedirectResponse(url="/signup?error=short", status_code=303)
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return RedirectResponse(url="/signup?error=exists", status_code=303)
    new_user = User(
        email=email,
        password=hash_password(password),
        name=name.strip()[:100],
        email_verified=not REQUIRE_VERIFICATION,
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
