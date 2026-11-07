"""Encrypt small secrets we must store (like a customer's API key) so they're unreadable in the database."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.auth import SECRET_KEY

_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(("secretbox:" + SECRET_KEY).encode()).digest()))


def seal(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode() if text else ""


def unseal(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return ""     # e.g. the app's SECRET_KEY changed; the customer re-enters it
