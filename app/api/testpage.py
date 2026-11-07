"""
A practice website at /test-page that the admin can switch between states, to try Uptraqr's
alerts for real: normal, small change, hacked, spam links, missing words, down, and a test API.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import SiteSetting

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STATES = {
    "normal": "Normal: the shop page as usual",
    "changed": "Page changed: new heading, prices and notice (a normal-looking update)",
    "hacked": "Hacked: page replaced with a hacker message",
    "spam": "Spam: hidden casino and pharmacy links added",
    "keyword": "Missing words: the \"Book a class\" button is gone",
    "down": "Down: the page returns a server error (503)",
}


def get_state(db) -> str:
    row = db.get(SiteSetting, "test_page_state")
    return row.value if row and row.value in STATES else "normal"


def set_state(db, state: str):
    if state not in STATES:
        state = "normal"
    row = db.get(SiteSetting, "test_page_state")
    if row:
        row.value = state
    else:
        db.add(SiteSetting(key="test_page_state", value=state))
    db.commit()


def _no_index(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/test-page", response_class=HTMLResponse)
def test_page(request: Request, db: Session = Depends(get_db)):
    state = get_state(db)
    if state == "down":
        return _no_index(HTMLResponse("<h1>503 Service Unavailable</h1>", status_code=503))
    return _no_index(templates.TemplateResponse("test_page.html", {"request": request, "state": state}))


@router.get("/test-page/api")
def test_api(db: Session = Depends(get_db)):
    """A pretend API: healthy normally, 'degraded' when changed, an error when down or hacked."""
    state = get_state(db)
    if state in ("down", "hacked"):
        return _no_index(JSONResponse({"status": "error"}, status_code=503))
    return _no_index(JSONResponse({"status": "degraded" if state in ("changed", "keyword") else "ok",
                                   "service": "Quillfern Pottery bookings"}))
