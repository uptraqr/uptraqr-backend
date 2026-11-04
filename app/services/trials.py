"""The free 14-day Pro trial: starting it, reminding people, and ending it gently."""
from datetime import datetime, timedelta

from app.core.abuse import canonical_email
from app.core.database import SessionLocal
from app.core.plans import TRIAL_DAYS, on_trial
from app.models.models import User, Monitor, TrialClaim


def can_start_trial(db, user) -> bool:
    """Only accounts that aren't paying and whose inbox has never had a trial."""
    if (user.plan or "free") != "free" or user.trial_ends_at:
        return False
    canon = user.email_canonical or canonical_email(user.email)
    return db.query(TrialClaim).filter(TrialClaim.email_canonical == canon).first() is None


def start_trial(db, user) -> bool:
    if not can_start_trial(db, user):
        return False
    user.trial_ends_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
    user.trial_notice = 0
    db.add(TrialClaim(email_canonical=user.email_canonical or canonical_email(user.email)))
    # Anything paused earlier (over the Free limit) comes back for the trial.
    from app.api.payments import apply_plan
    apply_plan(db, user, None)
    return True


def run_trial_checks(now=None):
    """Hourly: '3 days left' reminder, then end the trial and pause what Free doesn't include."""
    from app.api.payments import apply_plan
    from app.services.email_alerts import send_trial_reminder_email, send_trial_ended_email
    now = now or datetime.utcnow()
    db = SessionLocal()
    try:
        for user in db.query(User).filter(User.trial_ends_at.isnot(None), User.trial_notice < 2).all():
            try:
                if (user.plan or "free") != "free":
                    user.trial_notice = 2          # they bought a plan; nothing more to say about the trial
                elif user.trial_ends_at <= now:
                    before = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.is_active == True).count()
                    apply_plan(db, user, None)     # trial is over: Free limits apply, extras pause (not deleted)
                    db.flush()
                    after = db.query(Monitor).filter(Monitor.user_id == user.id, Monitor.is_active == True).count()
                    if user.email_verified:
                        send_trial_ended_email(user.email, max(before - after, 0))
                    user.trial_notice = 2
                elif user.trial_notice < 1 and user.trial_ends_at - now <= timedelta(days=3):
                    if user.email_verified:
                        days = max(1, int(-(-(user.trial_ends_at - now).total_seconds() // 86400)))
                        send_trial_reminder_email(user.email, days)
                    user.trial_notice = 1
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Trial check failed for user {user.id}: {e}")
    finally:
        db.close()
