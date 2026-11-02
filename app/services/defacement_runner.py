"""Runs defacement scans for monitors and records results / sends alerts."""
import json
from datetime import datetime

import requests

from app.core.database import SessionLocal
from app.models.models import Monitor, User, DefacementWatch, DefacementEvent
from app.services.defacement import build_baseline, scan, overall_status, findings_key, UnsafeURLError
from app.services.email_alerts import send_defacement_alert, send_defacement_cleared_alert
from app.services.sms_alerts import send_defacement_sms


def get_or_create_watch(db, monitor: Monitor) -> DefacementWatch:
    watch = db.query(DefacementWatch).filter(DefacementWatch.monitor_id == monitor.id).first()
    if not watch:
        watch = DefacementWatch(monitor_id=monitor.id, enabled=True, status="learning")
        db.add(watch)
        db.flush()
    return watch


def learn(db, monitor: Monitor, watch: DefacementWatch):
    """Take a fresh 'known good' snapshot of the page."""
    baseline = build_baseline(monitor.url)
    watch.baseline = json.dumps(baseline)
    watch.baseline_set_at = datetime.utcnow()
    watch.last_checked_at = watch.baseline_set_at
    watch.status = "ok"
    watch.last_findings = "[]"
    watch.last_error = None
    watch.last_alert_key = None


def resolve_open_events(db, monitor_id: int, resolution: str):
    for ev in db.query(DefacementEvent).filter(
        DefacementEvent.monitor_id == monitor_id, DefacementEvent.resolved_at.is_(None)
    ).all():
        ev.resolved_at = datetime.utcnow()
        ev.resolution = resolution


def check_monitor(db, monitor: Monitor, send_alerts: bool = True) -> DefacementWatch:
    watch = get_or_create_watch(db, monitor)
    if not watch.enabled:
        return watch
    try:
        if not watch.baseline:
            learn(db, monitor, watch)
            return watch

        result = scan(monitor.url, json.loads(watch.baseline))
        watch.last_checked_at = datetime.utcnow()
        if result["error"]:
            # The uptime checker already alerts on errors; just record it here.
            watch.last_error = result["error"]
            return watch

        findings = result["findings"]
        previous_status = watch.status
        watch.status = overall_status(findings)
        watch.last_findings = json.dumps(findings)
        watch.last_error = None
        key = findings_key(findings)

        if watch.status in ("changed", "suspicious") and key != watch.last_alert_key:
            db.add(DefacementEvent(monitor_id=monitor.id, status=watch.status, findings=watch.last_findings))
            watch.last_alert_key = key
            if send_alerts:
                user = db.query(User).filter(User.id == monitor.user_id).first()
                send_defacement_alert(monitor.name, monitor.url, watch.status, findings,
                                      user.email if user else None)
                if user and user.phone and watch.status == "suspicious":
                    send_defacement_sms(monitor.name, monitor.url, user.phone)
        elif watch.status == "ok" and previous_status in ("changed", "suspicious"):
            # The page went back to normal on its own (e.g. the owner restored a backup).
            resolve_open_events(db, monitor.id, "reverted")
            watch.last_alert_key = None
            if send_alerts:
                user = db.query(User).filter(User.id == monitor.user_id).first()
                send_defacement_cleared_alert(monitor.name, monitor.url, user.email if user else None)
    except UnsafeURLError as e:
        watch.status = "error"
        watch.last_error = str(e)
    except requests.RequestException:
        watch.last_error = "We couldn't load the page for this check."
    except Exception as e:  # never let one bad site stop the others
        watch.last_error = "Unexpected error during the check."
        print(f"Defacement check failed for monitor {monitor.id}: {e}")
    return watch


def run_defacement_checks():
    db = SessionLocal()
    try:
        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        for monitor in monitors:
            check_monitor(db, monitor)
            db.commit()
    finally:
        db.close()
