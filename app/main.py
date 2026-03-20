from fastapi import FastAPI
from app.core.database import init_db
from app.core.scheduler import start_scheduler, stop_scheduler

app = FastAPI(
    title="Uptraqr",
    description="Uptime monitoring platform for local businesses",
    version="0.1.0"
)

@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()

@app.on_event("shutdown")
def shutdown():
    stop_scheduler()

@app.get("/")
def root():
    return {
        "name": "Uptraqr",
        "status": "running",
        "version": "0.1.0"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}