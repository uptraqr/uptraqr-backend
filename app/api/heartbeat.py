"""
The check-in address for scheduled jobs (backups, nightly scripts, servers behind a firewall).
The customer's job visits /ping/<its secret code> each time it runs; if it goes quiet, we alert them.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.abuse import RateLimiter
from app.core.database import get_db
from app.models.models import Monitor

router = APIRouter()
ping_limiter = RateLimiter(limit=60, window=60)   # per job: plenty for real use, stops floods


@router.api_route("/ping/{token}", methods=["GET", "POST", "HEAD"], response_class=PlainTextResponse)
def ping(token: str, request: Request, db: Session = Depends(get_db)):
    if len(token) < 16 or len(token) > 64 or not ping_limiter.allow(token):
        return PlainTextResponse("Not found\n", status_code=404)
    m = db.query(Monitor).filter(Monitor.heartbeat_token == token, Monitor.kind == "heartbeat").first()
    if not m:
        return PlainTextResponse("Not found\n", status_code=404)
    if m.is_active:
        m.last_ping_at = datetime.utcnow()
        db.commit()
        return PlainTextResponse("OK\n")
    return PlainTextResponse("Paused\n")
