"""
"Continue with Google" sign-in (OAuth 2.0 / OpenID Connect).
Switched on only when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set.
"""
import hmac
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from jose import jwt as _jwt
from sqlalchemy.orm import Session

from app.core.abuse import canonical_email, is_disposable, client_ip, signup_limiter
from app.core.auth import hash_password
from app.core.database import get_db
from app.core.timefmt import clean_tz
from app.models.models import User

router = APIRouter()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
ENABLED = bool(CLIENT_ID and CLIENT_SECRET)
SITE_URL = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
REDIRECT_URI = f"{SITE_URL}/auth/google/callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "g_state"


def template_globals(env):
    env.globals["google_enabled"] = ENABLED


def _fail(where="login", code="google"):
    r = RedirectResponse(f"/{where}?error={code}", status_code=303)
    r.delete_cookie(STATE_COOKIE, path="/auth/google")
    return r


@router.get("/auth/google")
def google_start(request: Request, tz: str = "", from_: str = ""):
    if not ENABLED:
        return RedirectResponse("/login", status_code=303)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
    }
    r = RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=303)
    # Remember what we sent so the reply can't be forged or replayed (10 minutes, this path only).
    r.set_cookie(STATE_COOKIE, f"{state}.{nonce}.{clean_tz(tz)}", max_age=600, httponly=True,
                 secure=True, samesite="lax", path="/auth/google")
    return r


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    from app.api.auth_routes import _login_response
    if not ENABLED:
        return RedirectResponse("/login", status_code=303)
    if error:                       # they pressed Cancel on Google's screen
        return _fail(code="google_cancel")
    saved = request.cookies.get(STATE_COOKIE, "")
    parts = saved.split(".", 2)
    if len(parts) != 3 or not state or not hmac.compare_digest(parts[0], state) or not code:
        return _fail()
    _, nonce, tz = parts
    try:
        resp = requests.post(TOKEN_URL, data={
            "code": code, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code",
        }, timeout=10)
        if resp.status_code != 200:
            return _fail()
        # Received straight from Google over HTTPS, so its contents can be trusted; we still check every field.
        claims = _jwt.get_unverified_claims(resp.json()["id_token"])
    except (requests.RequestException, KeyError, ValueError, Exception):
        return _fail()
    if (claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or claims.get("aud") != CLIENT_ID or int(claims.get("exp", 0)) < time.time()
            or not hmac.compare_digest(str(claims.get("nonce", "")), nonce)
            or not claims.get("email") or claims.get("email_verified") not in (True, "true")):
        return _fail()

    email = claims["email"].strip()[:254]
    canon = canonical_email(email)
    user = db.query(User).filter(User.email == email).first() or \
        db.query(User).filter(User.email_canonical == canon).first()
    if user:
        if not user.email_verified:
            user.email_verified = True      # Google has confirmed they own this inbox
            db.commit()
    else:
        if is_disposable(email):
            return _fail("signup", "disposable")
        if not signup_limiter.allow(client_ip(request)):
            return _fail("signup", "limit")
        user = User(
            email=email, email_canonical=canon,
            name=(claims.get("name") or email.split("@")[0])[:100],
            password=hash_password(secrets.token_urlsafe(32)), password_set=False,
            email_verified=True, timezone=clean_tz(tz),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        from app.services.trials import start_trial
        if start_trial(db, user):
            db.commit()
    r = _login_response(user)
    r.delete_cookie(STATE_COOKIE, path="/auth/google")
    return r
