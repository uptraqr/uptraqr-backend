from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.database import init_db
from app.core.scheduler import start_scheduler, stop_scheduler
from app.api.monitors import router as monitors_router
from app.api.dashboard import router as dashboard_router
from app.api.auth_routes import router as auth_router
from app.api.status import router as status_router
from app.api.admin import router as admin_router
from app.api.payments import router as payments_router

app = FastAPI(
    title="Uptraqr",
    description="Uptime monitoring platform for local businesses",
    version="0.1.0",
    docs_url="/docs" if os.getenv("ENVIRONMENT") != "production" else None,
    redoc_url="/redoc" if os.getenv("ENVIRONMENT") != "production" else None,
    openapi_url="/openapi.json" if os.getenv("ENVIRONMENT") != "production" else None
)

templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "404.html", 
            {"request": request}, 
            status_code=404
        )
    return templates.TemplateResponse(
        "404.html",
        {"request": request},
        status_code=exc.status_code
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return templates.TemplateResponse(
        "404.html",
        {"request": request},
        status_code=500
    )

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

@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})

app.include_router(monitors_router, prefix="/api")
app.include_router(dashboard_router)
app.include_router(auth_router, prefix="/api")
app.include_router(auth_router)
app.include_router(status_router)
app.include_router(admin_router)
app.include_router(payments_router, prefix="/api")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
