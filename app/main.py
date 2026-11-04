from dotenv import load_dotenv
load_dotenv()

import os
import secrets
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlparse
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
from app.api.report import router as report_router
from app.api.account import router as account_router
from app.api.heartbeat import router as heartbeat_router

app = FastAPI(
    title="Uptraqr",
    description="Uptime monitoring platform for local businesses",
    version="0.1.0",
    # The API docs pages are only switched on for local development, never on the live site.
    docs_url="/docs" if os.getenv("ENVIRONMENT") == "development" else None,
    redoc_url="/redoc" if os.getenv("ENVIRONMENT") == "development" else None,
    openapi_url="/openapi.json" if os.getenv("ENVIRONMENT") == "development" else None
)

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
# The one official address of the site. Used for canonical links, the sitemap
# and share previews, so Google never treats the Railway address as a copy.
SITE_URL = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
SITE_HOST = urlparse(SITE_URL).hostname
templates.env.globals["site_url"] = SITE_URL
from app.core.plans import PLANS as _PLANS
templates.env.globals["PLANS"] = _PLANS
from app.core import turnstile as _turnstile
_turnstile.template_globals(templates.env)


# ---------------- Security headers ----------------
# Sent with every response. They tell browsers to block common attacks:
# injected scripts (CSP), clickjacking (frame-ancestors / X-Frame-Options),
# downgrade to plain http (HSTS), and content-type tricks (nosniff).
@app.middleware("http")
async def security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce   # templates put this on their <script> tags
    response = await call_next(request)
    h = response.headers
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        h["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://challenges.cloudflare.com; "
            "frame-src https://challenges.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
    # Any address other than the official one (e.g. the *.up.railway.app address)
    # tells search engines not to list it, so it can't compete with www.uptraqr.com.
    if request.url.hostname != SITE_HOST:
        h["X-Robots-Tag"] = "noindex"
    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # API calls (from the dashboard's JavaScript) need a JSON error message,
    # not the 404 web page, so the dashboard can show what went wrong.
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
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
    print(f"Unhandled error on {request.url.path}: {exc!r}")
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)
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

PUBLIC_PAGES = ["/", "/pricing", "/features/website-defacement-monitoring",
                "/features/uptime-monitoring", "/features/ssl-certificate-monitoring",
                "/features/website-health-check", "/privacy", "/terms"]

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /dashboard\n"
        "Disallow: /admin\n"
        "Disallow: /api/\n"
        "Disallow: /logout\n"
        "Disallow: /account\n"
        "Disallow: /unsubscribe\n"
        "Disallow: /ping/\n"
        f"\nSitemap: {SITE_URL}/sitemap.xml\n"
    )

@app.get("/sitemap.xml")
def sitemap():
    urls = "".join(f"<url><loc>{SITE_URL}{p}</loc></url>" for p in PUBLIC_PAGES)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")

FEATURE_PAGES = {
    "website-defacement-monitoring": "feature_defacement.html",
    "uptime-monitoring": "feature_uptime.html",
    "ssl-certificate-monitoring": "feature_ssl.html",
    "website-health-check": "feature_health.html",
}

@app.get("/features/{slug}", response_class=HTMLResponse)
def feature_page(slug: str, request: Request):
    page = FEATURE_PAGES.get(slug)
    if not page:
        raise StarletteHTTPException(status_code=404)
    return templates.TemplateResponse(page, {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(monitors_router, prefix="/api")
app.include_router(dashboard_router)
app.include_router(auth_router, prefix="/api")
app.include_router(auth_router)
app.include_router(status_router)
app.include_router(admin_router)
app.include_router(report_router)
app.include_router(account_router)
app.include_router(heartbeat_router)
app.include_router(payments_router, prefix="/api")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
