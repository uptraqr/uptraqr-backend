from apscheduler.schedulers.background import BackgroundScheduler
from app.services.checker import run_checks

scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(run_checks, "interval", minutes=5)
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()