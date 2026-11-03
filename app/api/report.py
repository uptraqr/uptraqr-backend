import os
import time

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.abuse import client_ip, RateLimiter
from app.services.report import run_report, normalise_url
from app.services.safe_fetch import UnsafeURLError

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["support_email"] = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
from app.core import turnstile as _turnstile
_turnstile.template_globals(templates.env)
templates.env.globals["site_url"] = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")

report_limiter = RateLimiter(limit=5, window=3600)   # 5 new reports per connection per hour
_cache = {}                                            # url -> (time, report): repeat views don't re-scan
CACHE_SECONDS = 600


def get_report(url: str):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    report = run_report(url)
    _cache[url] = (time.time(), report)
    if len(_cache) > 500:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:250]:
            _cache.pop(k, None)
    return report


@router.get("/check", response_class=HTMLResponse)
def check_page(request: Request, url: str = ""):
    if not url.strip():
        return RedirectResponse("/#check", status_code=302)
    ctx = {"request": request, "entered": url.strip()[:300], "report": None, "error": None}
    try:
        norm = normalise_url(url)
        cached = _cache.get(norm)
        if not (cached and time.time() - cached[0] < CACHE_SECONDS) and not report_limiter.allow(client_ip(request)):
            ctx["error"] = "You've checked 5 websites in the last hour. Please wait a little and try again."
            return templates.TemplateResponse("report.html", ctx, status_code=429)
        ctx["report"] = get_report(norm)
    except UnsafeURLError as e:
        ctx["error"] = str(e)
    except requests.exceptions.Timeout:
        ctx["error"] = "That website took too long to answer (over 15 seconds). It may be down or very slow."
    except requests.RequestException:
        ctx["error"] = "We couldn't connect to that website. Check the address, or the site may be down."
    except Exception as e:
        print(f"Report failed for {url!r}: {e!r}")
        ctx["error"] = "Something went wrong while checking that website. Please try again."
    return templates.TemplateResponse("report.html", ctx, status_code=200 if ctx["report"] else 400)
