"""
Once a day: look up when each website's domain name registration expires
(using RDAP, the official public registry lookup) and email reminders
30, 14, 7, 1 and 0 days before. Included on every plan.
"""
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
import tldextract

from app.core.database import SessionLocal
from app.models.models import Monitor, User, DomainState
from app.services.email_alerts import send_domain_alert
from app.services.safe_fetch import USER_AGENT

THRESHOLDS = [30, 14, 7, 1, 0]
RDAP = "https://rdap.org/domain/"
# Uses the public-suffix list bundled with the library, so it works without downloading anything.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def registered_domain(url: str):
    """shop.example.co.uk -> example.co.uk (None for IP addresses)."""
    host = urlparse(url).hostname or ""
    return _extract(host).registered_domain or None


def lookup_expiry(domain: str):
    """The registration expiry date, or None if the registry doesn't publish it."""
    try:
        r = requests.get(RDAP + domain, timeout=15, headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json"})
        if r.status_code != 200:
            return None
        for ev in r.json().get("events", []):
            if ev.get("eventAction") == "expiration" and ev.get("eventDate"):
                return datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00")).replace(tzinfo=None)
    except (requests.RequestException, ValueError):
        return None
    return None


def threshold_for(days_left: int):
    reached = [t for t in THRESHOLDS if days_left <= t]
    return min(reached) if reached else None


def check_monitor_domain(db, monitor, user, cache=None, lookup=None, send=None):
    lookup = lookup or lookup_expiry
    send = send or send_domain_alert
    state = db.query(DomainState).filter(DomainState.monitor_id == monitor.id).first()
    if not state:
        state = DomainState(monitor_id=monitor.id)
        db.add(state)
    state.last_checked_at = datetime.utcnow()
    domain = registered_domain(monitor.url)
    if not domain:
        state.domain, state.expiry_date = None, None
        return state
    if cache is not None and domain in cache:
        expiry = cache[domain]
    else:
        expiry = lookup(domain)
        if cache is not None:
            cache[domain] = expiry
    renewed = state.expiry_date and expiry and (expiry - state.expiry_date).days >= 1
    if state.domain != domain or renewed:
        state.last_threshold = None          # renewed (or a different domain): start the reminders over
    state.domain, state.expiry_date = domain, expiry
    if not expiry:
        return state
    days_left = (expiry - datetime.utcnow()).days
    step = threshold_for(days_left)
    if step is not None and (state.last_threshold is None or step < state.last_threshold):
        if user and user.email_alerts:
            send(monitor.name, domain, days_left, expiry, user.email, tz=user.timezone)
        state.last_threshold = step
    return state


def run_domain_checks():
    db = SessionLocal()
    cache = {}
    try:
        owners = {u.id: u for u in db.query(User).all()}
        for monitor in db.query(Monitor).filter(Monitor.is_active == True, Monitor.kind == "website").all():
            try:
                check_monitor_domain(db, monitor, owners.get(monitor.user_id), cache)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Domain check failed for monitor {monitor.id}: {e}")
    finally:
        db.close()
