"""On the 1st of each month, email paid customers a summary of last month for each website."""
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.core.plans import plan_key
from app.models.models import User, Monitor, Incident, DefacementWatch, SslAlertState
from app.services.history import uptime_percent
from app.services.email_alerts import send_monthly_report_email

TAMPER_WORDS = {"ok": "No tampering", "learning": "Tamper watch learning",
                "changed": "Page changed", "suspicious": "Possible hack", "error": "Tamper watch error"}


def _site_summary(db, monitor, now):
    from app.api.report import get_report
    month_ago = now - timedelta(days=30)
    incidents = db.query(Incident).filter(Incident.monitor_id == monitor.id,
                                          Incident.started_at >= month_ago).count()
    watch = db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).first()
    ssl = db.query(SslAlertState).filter(SslAlertState.monitor_id == monitor.id).first()
    try:
        ssl_days = (datetime.fromisoformat(ssl.expiry_date) - now).days if ssl and ssl.expiry_date else None
    except ValueError:
        ssl_days = None
    try:
        grade = get_report(monitor.url)["grade"]
    except Exception:
        grade = None
    return {
        "name": monitor.name, "url": monitor.url,
        "uptime": uptime_percent(db, monitor.id, 30, now=now),
        "incidents": incidents,
        "grade": grade,
        "tamper": TAMPER_WORDS.get(watch.status, "Tamper watch on") if watch else "Tamper watch starting",
        "ssl_days": ssl_days,
    }


def send_monthly_reports(now=None):
    now = now or datetime.utcnow()
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%B %Y")
    db = SessionLocal()
    sent = 0
    try:
        for user in db.query(User).filter(User.monthly_reports == True, User.email_verified == True).all():
            if plan_key(user) == "free":
                continue
            monitors = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.is_active == True).all()
            if not monitors:
                continue
            try:
                sites = [_site_summary(db, m, now) for m in monitors]
                if send_monthly_report_email(user.email, last_month, sites):
                    sent += 1
            except Exception as e:  # one customer's problem shouldn't stop everyone else's report
                print(f"Monthly report failed for user {user.id}: {e}")
    finally:
        db.close()
    print(f"Monthly reports sent: {sent}")
    return sent
