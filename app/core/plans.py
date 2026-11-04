"""
One place that defines what each plan gets. Everything else (limits, check
speed, tamper watch, history) reads from here, so the website, the code and
what customers pay for always match.
"""

PLANS = {
    "free": {
        "label": "Free",
        "price_cad": 0,
        "sites": 1,
        "check_minutes": 5,        # uptime check interval
        "tamper_minutes": None,    # None = tamper watch locked
        "history_days": 0,         # no history shown
        "servers": False,          # port and heartbeat checks locked
    },
    "starter": {
        "label": "Starter",
        "price_cad": 10,
        "sites": 5,
        "check_minutes": 2,
        "tamper_minutes": 30,
        "history_days": 30,
        "servers": True,
    },
    "pro": {
        "label": "Pro",
        "price_cad": 25,
        "sites": 15,
        "check_minutes": 1,
        "tamper_minutes": 10,
        "history_days": 90,
        "servers": True,
    },
    "agency": {
        "label": "Agency",
        "price_cad": 65,
        "sites": 50,
        "check_minutes": 1,
        "tamper_minutes": 10,
        "history_days": 365,
        "servers": True,
    },
}

DETAIL_DAYS = 7          # every individual check is kept this long (paid plans)
FREE_DETAIL_HOURS = 24   # free plans keep only the last day, for the dashboard


TRIAL_DAYS = 14
TRIAL_PLAN = "pro"


def on_trial(user) -> bool:
    """True while a non-paying account is inside its free Pro trial."""
    from datetime import datetime
    ends = getattr(user, "trial_ends_at", None)
    paying = (getattr(user, "plan", None) or "free").lower() in PLANS and (user.plan or "free").lower() != "free"
    return bool(ends and not paying and datetime.utcnow() < ends)


def trial_days_left(user) -> int:
    from datetime import datetime
    if not on_trial(user):
        return 0
    secs = (user.trial_ends_at - datetime.utcnow()).total_seconds()
    return max(1, int(-(-secs // 86400)))   # round up: "1 day left" until it's over


def plan_key(user) -> str:
    """The user's plan key; a paid plan wins, then an active trial, otherwise free."""
    key = (getattr(user, "plan", None) or "free").lower()
    if key in PLANS and key != "free":
        return key
    return TRIAL_PLAN if on_trial(user) else "free"


def plan_for(user) -> dict:
    return PLANS[plan_key(user)]
