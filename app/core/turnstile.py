"""
Cloudflare Turnstile: an invisible "are you human?" check on forms bots could abuse.

If TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY aren't set, the check is switched
off, so the site keeps working before the keys are added.
"""
import os

import requests

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SITE_KEY = (os.getenv("TURNSTILE_SITE_KEY") or "").strip()
SECRET_KEY = (os.getenv("TURNSTILE_SECRET_KEY") or "").strip()
ENABLED = bool(SITE_KEY and SECRET_KEY)


def verify(token: str, ip: str = "") -> bool:
    """True if the visitor passed the check (or the check is switched off)."""
    if not ENABLED:
        return True
    if not token or len(token) > 2048:
        return False
    try:
        r = requests.post(VERIFY_URL, data={"secret": SECRET_KEY, "response": token, "remoteip": ip}, timeout=6)
        return bool(r.json().get("success"))
    except Exception as e:
        # Fail closed: if we can't confirm the visitor is human, don't let the form through.
        print(f"Turnstile check failed: {e!r}")
        return False


def template_globals(env):
    env.globals["turnstile_site_key"] = SITE_KEY if ENABLED else ""
