"""
History and tidy-up.

Every check is kept for a short time (7 days on paid plans, 24 hours on Free).
Before old checks are deleted they are rolled up into one summary per site per
day, which is kept for the plan's history length (30/90/365 days). Outages are
kept for the same length. This keeps the database small: a year of daily
summaries is 365 tiny rows per site instead of ~500,000 checks.
"""
from datetime import datetime, timedelta, date

from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.plans import plan_for, DETAIL_DAYS, FREE_DETAIL_HOURS
from app.models.models import Monitor, User, CheckResult, Incident, DailySummary


def roll_up_day(db, monitor_id: int, day: date):
    """Create or refresh the summary row for one site and one (UTC) day from its detailed checks."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    rows = db.query(CheckResult.is_up, CheckResult.response_time).filter(
        CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= start, CheckResult.checked_at < end
    ).all()
    if not rows:
        return None
    times = [r for _, r in rows if r is not None]
    summary = db.query(DailySummary).filter(DailySummary.monitor_id == monitor_id, DailySummary.day == day).first()
    if not summary:
        summary = DailySummary(monitor_id=monitor_id, day=day)
        db.add(summary)
    summary.checks = len(rows)
    summary.up_checks = sum(1 for up, _ in rows if up)
    summary.avg_response = round(sum(times) / len(times), 3) if times else None
    summary.max_response = round(max(times), 3) if times else None
    return summary


def tidy_up(now=None):
    """Nightly: summarise finished days, then delete what each plan no longer keeps."""
    now = now or datetime.utcnow()
    today = now.date()
    db = SessionLocal()
    try:
        owners = {u.id: u for u in db.query(User).all()}
        for m in db.query(Monitor).all():
            plan = plan_for(owners.get(m.user_id))
            keep_days = plan["history_days"]
            # 1) summarise every finished day that still has detailed checks
            #    (each finished day is summarised once, while all its checks still exist)
            if keep_days:
                first = db.query(func.min(CheckResult.checked_at)).filter(CheckResult.monitor_id == m.id).scalar()
                if first:
                    done = {d for (d,) in db.query(DailySummary.day).filter(DailySummary.monitor_id == m.id).all()}
                    d = first.date()
                    while d < today:
                        if d not in done:
                            roll_up_day(db, m.id, d)
                        d += timedelta(days=1)
            # 2) delete detailed checks past the detail window
            detail_cutoff = now - (timedelta(days=DETAIL_DAYS) if keep_days else timedelta(hours=FREE_DETAIL_HOURS))
            db.query(CheckResult).filter(CheckResult.monitor_id == m.id, CheckResult.checked_at < detail_cutoff) \
                .delete(synchronize_session=False)
            # 3) delete summaries and finished outages past the plan's history length
            history_cutoff = now - timedelta(days=keep_days) if keep_days else now - timedelta(hours=FREE_DETAIL_HOURS)
            db.query(DailySummary).filter(DailySummary.monitor_id == m.id, DailySummary.day < history_cutoff.date()) \
                .delete(synchronize_session=False)
            db.query(Incident).filter(Incident.monitor_id == m.id, Incident.is_resolved == True,
                                      Incident.resolved_at < history_cutoff).delete(synchronize_session=False)
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"History tidy-up failed: {e}")
    finally:
        db.close()


def uptime_percent(db, monitor_id: int, days: int, now=None):
    """Uptime over the last `days` days, combining daily summaries with recent detailed checks."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    total = up = 0
    summarised_days = set()
    for s in db.query(DailySummary).filter(DailySummary.monitor_id == monitor_id, DailySummary.day >= since.date()).all():
        total += s.checks or 0
        up += s.up_checks or 0
        summarised_days.add(s.day)
    for is_up, at in db.query(CheckResult.is_up, CheckResult.checked_at).filter(
            CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= since).all():
        if at.date() in summarised_days:
            continue  # already counted in that day's summary
        total += 1
        up += 1 if is_up else 0
    return round(up / total * 100, 2) if total else None


def daily_bars(db, monitor_id: int, days: int, now=None):
    """Per-day uptime for the history strip: oldest first, None for days with no data."""
    now = now or datetime.utcnow()
    today = now.date()
    start = today - timedelta(days=days - 1)
    by_day = {s.day: s for s in db.query(DailySummary).filter(DailySummary.monitor_id == monitor_id, DailySummary.day >= start).all()}
    # days not yet summarised (recent ones) come from detailed checks
    recent = {}
    for is_up, at in db.query(CheckResult.is_up, CheckResult.checked_at).filter(
            CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= datetime.combine(start, datetime.min.time())).all():
        t, u = recent.get(at.date(), (0, 0))
        recent[at.date()] = (t + 1, u + (1 if is_up else 0))
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d in by_day and by_day[d].checks:
            out.append({"day": d.isoformat(), "uptime": round(by_day[d].up_checks / by_day[d].checks * 100, 2)})
        elif d in recent:
            t, u = recent[d]
            out.append({"day": d.isoformat(), "uptime": round(u / t * 100, 2)})
        else:
            out.append({"day": d.isoformat(), "uptime": None})
    return out
