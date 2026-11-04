from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.services.checker import run_checks
from app.services.defacement_runner import run_defacement_checks
from app.services.ssl_runner import run_ssl_checks
from app.services.history import tidy_up
from app.services.monthly_report import send_monthly_reports
from app.services.domain_runner import run_domain_checks
from app.services.trials import run_trial_checks

scheduler = BackgroundScheduler()

def start_scheduler():
    # Every minute: each site is checked only when its plan's interval is up (5/2/1 min).
    scheduler.add_job(run_checks, "interval", minutes=1, max_instances=1, coalesce=True)
    # Every 10 minutes: tamper scans at each plan's speed (30 or 10 min; off on Free).
    # First run shortly after start-up so new sites get their snapshot quickly.
    scheduler.add_job(run_defacement_checks, "interval", minutes=10, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=2))
    # SSL certificates: once a day, first run 5 minutes after start-up.
    scheduler.add_job(run_ssl_checks, "interval", hours=24, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=5))
    # Nightly at 03:15 UTC: summarise yesterday and delete data each plan no longer keeps.
    scheduler.add_job(tidy_up, "cron", hour=3, minute=15, max_instances=1, coalesce=True)
    # Domain name expiry: once a day, first run 8 minutes after start-up.
    scheduler.add_job(run_domain_checks, "interval", hours=24, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=8))
    # Free trials: reminders and endings, checked every hour.
    scheduler.add_job(run_trial_checks, "interval", hours=1, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=3))
    # 1st of each month at 15:20 UTC (morning in Canada): monthly report for paid plans.
    scheduler.add_job(send_monthly_reports, "cron", day=1, hour=15, minute=20, max_instances=1, coalesce=True)
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()
