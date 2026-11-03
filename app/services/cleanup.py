"""Delete a website or a whole account together with everything stored about it."""
from app.models.models import (Monitor, CheckResult, Incident, DefacementWatch, DefacementEvent,
                               SslAlertState, DailySummary)


def delete_monitor_rows(db, monitor: Monitor):
    # Child rows first: PostgreSQL refuses to delete a website that still has history pointing at it.
    for model in (CheckResult, Incident, DefacementWatch, DefacementEvent, SslAlertState, DailySummary):
        db.query(model).filter(model.monitor_id == monitor.id).delete(synchronize_session=False)
    db.delete(monitor)


def delete_user_everything(db, user):
    for monitor in db.query(Monitor).filter(Monitor.user_id == user.id).all():
        delete_monitor_rows(db, monitor)
    db.flush()
    db.delete(user)
