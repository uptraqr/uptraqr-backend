import requests
from datetime import datetime
from app.core.database import SessionLocal
from app.models.models import Monitor, CheckResult, Incident
from app.services.email_alerts import send_down_alert, send_recovery_alert

def check_url(url: str):
    try:
        response = requests.get(url, timeout=10)
        return {
            "is_up": True,
            "status_code": response.status_code,
            "response_time": response.elapsed.total_seconds()
        }
    except requests.exceptions.RequestException:
        return {
            "is_up": False,
            "status_code": None,
            "response_time": None
        }

def run_checks():
    db = SessionLocal()
    try:
        monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
        for monitor in monitors:
            result = check_url(monitor.url)
            check = CheckResult(
                monitor_id=monitor.id,
                status_code=result["status_code"],
                response_time=result["response_time"],
                is_up=result["is_up"],
                checked_at=datetime.utcnow()
            )
            db.add(check)

            if not result["is_up"]:
                existing = db.query(Incident).filter(
                    Incident.monitor_id == monitor.id,
                    Incident.is_resolved == False
                ).first()
                if not existing:
                    incident = Incident(monitor_id=monitor.id)
                    db.add(incident)
                    send_down_alert(monitor.name, monitor.url)
            else:
                open_incident = db.query(Incident).filter(
                    Incident.monitor_id == monitor.id,
                    Incident.is_resolved == False
                ).first()
                if open_incident:
                    open_incident.is_resolved = True
                    open_incident.resolved_at = datetime.utcnow()
                    send_recovery_alert(monitor.name, monitor.url)

            db.commit()
    finally:
        db.close()