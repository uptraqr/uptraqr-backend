import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Cookie, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User

load_dotenv()

# The key that signs every login. It must come from a hidden setting
# (environment variable), never from the code, or anyone reading the
# code could create fake logins.
SECRET_KEY = (os.getenv("SECRET_KEY") or "").strip()
if len(SECRET_KEY) < 32:
    # Never print the key itself, only what's wrong with it.
    reason = "is not set at all" if not SECRET_KEY else f"is only {len(SECRET_KEY)} characters long (needs 32 or more)"
    others = sorted(k for k in os.environ if "SECRET" in k.upper())
    raise RuntimeError(
        f"SECRET_KEY {reason}. Add it under this service's Variables tab. "
        f"Secret-like variable names this app can see: {others}"
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def hash_password(password: str):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str):
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        # Email-confirmation links are signed with the same key; never accept one as a login.
        if email is None or payload.get("purpose"):
            raise HTTPException(status_code=401, detail="Not authenticated")
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    try:
        return get_current_user(request, db)
    except:
        return None

VERIFY_HOURS = 24

def create_verify_token(email: str) -> str:
    """A link token that can only confirm an email address, valid for 24 hours."""
    exp = datetime.utcnow() + timedelta(hours=VERIFY_HOURS)
    return jwt.encode({"sub": email, "purpose": "verify-email", "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def read_verify_token(token: str):
    """Return the email address in a valid confirmation token, or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != "verify-email":
        return None
    return payload.get("sub")
