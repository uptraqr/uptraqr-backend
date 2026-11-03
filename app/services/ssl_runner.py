"""Daily SSL certificate check: emails reminders 30, 14, 7, 3, 1 and 0 days before expiry."""
from datetime import datetime
from urllib.parse import urlparse

from app.core.database import SessionLocal
from app.models.models import Monitor, User, SslAlertState
from app.services.ssl_checker import check_ssl
from app.services.safe_fetch import check_url_is_safe, UnsafeURLError
from app.services.email_alerts import send_ssl_alert

THRESHOLDS = [30, 14, 7, 3, 1, 0]


def threshold_for(days_left: int):
    """The smallest reminder step the certificate has reached, or None if more than 30 days left."""
    reached = [t for t in THRESHOLDS if days_left <= t]
    return min(reached) if reached else None


def check_monitor_ssl(db, monitor: Monitor, send=send_ssl_alert):
    parsed = urlparse(monitor.url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    try:
        check_url_is_safe(monitor.url)
    except UnsafeURLError:
        return None
    result = check_ssl(parsed.hostname)
    state = db.query(SslAlertState).filter(SslAlertState.monitor_id == monitor.id).first()
    if not state:
        state = SslAlertState(monitor_id=monitor.id)
        db.add(state)
    state.last_checked_at = datetime.utcnow()
    if not result.get("valid"):
        return result
    # A renewed certificate has a new expiry date: start the reminder steps again.
    if state.expiry_date != result["expiry_date"]:
        state.expiry_date = result["expiry_date"]
        state.last_threshold = None
    step = threshold_for(result["days_left"])
    if step is not None and (state.last_threshold is None or step < state.last_threshold):
        user = db.query(User).filter(User.id == monitor.user_id).first()
        send(monitor.name, monitor.url, max(result["days_left"], 0), user.email if user else None)
        state.last_threshold = step
    return result


def run_ssl_checks():
    db = SessionLocal()
    try:
        for monitor in db.query(Monitor).filter(Monitor.is_active == True).all():
            try:
                check_monitor_ssl(db, monitor)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"SSL check failed for monitor {monitor.id}: {e}")
    finally:
        db.close()
