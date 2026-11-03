from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.services.checker import run_checks
from app.services.defacement_runner import run_defacement_checks
from app.services.ssl_runner import run_ssl_checks

scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(run_checks, "interval", minutes=5, max_instances=1, coalesce=True)
    # Defacement scan every 30 minutes; first run shortly after start-up so new
    # sites get their "known good" snapshot quickly.
    scheduler.add_job(run_defacement_checks, "interval", minutes=30, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=2))
    # SSL certificates: once a day, first run 5 minutes after start-up.
    scheduler.add_job(run_ssl_checks, "interval", hours=24, max_instances=1, coalesce=True,
                      next_run_time=datetime.now() + timedelta(minutes=5))
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()
