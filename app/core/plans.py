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
    },
    "starter": {
        "label": "Starter",
        "price_cad": 10,
        "sites": 5,
        "check_minutes": 2,
        "tamper_minutes": 30,
        "history_days": 30,
    },
    "pro": {
        "label": "Pro",
        "price_cad": 25,
        "sites": 15,
        "check_minutes": 1,
        "tamper_minutes": 10,
        "history_days": 90,
    },
    "agency": {
        "label": "Agency",
        "price_cad": 65,
        "sites": 50,
        "check_minutes": 1,
        "tamper_minutes": 10,
        "history_days": 365,
    },
}

DETAIL_DAYS = 7          # every individual check is kept this long (paid plans)
FREE_DETAIL_HOURS = 24   # free plans keep only the last day, for the dashboard


def plan_key(user) -> str:
    """The user's plan key; anything unknown or empty counts as free."""
    key = (getattr(user, "plan", None) or "free").lower()
    return key if key in PLANS else "free"


def plan_for(user) -> dict:
    return PLANS[plan_key(user)]
