"""Show times in each customer's own time zone."""
from datetime import datetime, timezone
import zoneinfo
from zoneinfo import ZoneInfo, available_timezones

# Always use the up-to-date time zone list installed with the app (the tzdata package),
# not whatever older copy the server has. Rules change: BC moved to permanent UTC-7 in Nov 2026.
zoneinfo.reset_tzpath([])

DEFAULT_TZ = "America/Vancouver"
_VALID = available_timezones()

# The choices shown on the Account page (most customers are in Canada).
TZ_CHOICES = [
    ("Canada", [
        ("America/Vancouver", "British Columbia (Vancouver, Surrey)"),
        ("America/Edmonton", "Mountain (Edmonton, Calgary)"),
        ("America/Dawson_Creek", "Mountain, no daylight saving (Dawson Creek, Fort St. John)"),
        ("America/Regina", "Central, no daylight saving (Saskatchewan)"),
        ("America/Winnipeg", "Central (Winnipeg)"),
        ("America/Toronto", "Eastern (Toronto, Ottawa, Montreal)"),
        ("America/Halifax", "Atlantic (Halifax)"),
        ("America/St_Johns", "Newfoundland (St. John's)"),
        ("America/Whitehorse", "Yukon (Whitehorse)"),
    ]),
    ("United States", [
        ("America/Los_Angeles", "Pacific (Los Angeles, Seattle)"),
        ("America/Denver", "Mountain (Denver)"),
        ("America/Phoenix", "Arizona"),
        ("America/Chicago", "Central (Chicago)"),
        ("America/New_York", "Eastern (New York)"),
        ("America/Anchorage", "Alaska"),
        ("Pacific/Honolulu", "Hawaii"),
    ]),
    ("Elsewhere", [
        ("Europe/London", "UK (London)"),
        ("Europe/Paris", "Central Europe (Paris, Berlin)"),
        ("Asia/Dubai", "Gulf (Dubai)"),
        ("Asia/Karachi", "Pakistan (Karachi)"),
        ("Asia/Kolkata", "India (Mumbai, Delhi)"),
        ("Asia/Singapore", "Singapore"),
        ("Asia/Manila", "Philippines (Manila)"),
        ("Australia/Sydney", "Australia East (Sydney)"),
        ("Pacific/Auckland", "New Zealand (Auckland)"),
        ("UTC", "UTC"),
    ]),
]
_LABELS = {k: v for _, group in TZ_CHOICES for k, v in group}


def clean_tz(name) -> str:
    """A real time zone name, or the default if it's missing or made up."""
    name = (name or "").strip()
    return name if name in _VALID else DEFAULT_TZ


def tz_label(name) -> str:
    return _LABELS.get(name, name)


def local(dt=None, tz=None) -> datetime:
    """A UTC time (naive, as stored in the database) converted to the customer's zone."""
    dt = dt or datetime.utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(clean_tz(tz)))


def fmt(dt=None, tz=None, with_date=True) -> str:
    """e.g. 'Nov 4, 2026, 4:17 am PST' (or just '4:17 am PST')."""
    t = local(dt, tz)
    hour = t.strftime("%I").lstrip("0") or "12"
    clock = f"{hour}:{t.strftime('%M')} {t.strftime('%p').lower()} {t.strftime('%Z')}"
    return f"{t.strftime('%b')} {t.day}, {t.year}, {clock}" if with_date else clock
