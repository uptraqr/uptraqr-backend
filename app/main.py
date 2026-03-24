from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.core.database import init_db
from app.core.scheduler import start_scheduler, stop_scheduler
from app.api.monitors import router as monitors_router
from app.api.dashboard import router as dashboard_router
from app.api.auth_routes import router as auth_router

app = FastAPI(
    title="Uptraqr",
    description="Uptime monitoring platform for local businesses",
    version="0.1.0"
)

templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()

@app.on_event("shutdown")
def shutdown():
    stop_scheduler()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "healthy"}

app.include_router(monitors_router, prefix="/api")
app.include_router(dashboard_router)
app.include_router(auth_router, prefix="/api")