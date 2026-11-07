import os

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional
from app.core.database import get_db
from app.core.plans import PLANS, plan_for
from app.models.models import User, Monitor
from app.services.stripe_service import create_checkout_session

router = APIRouter()
SITE_URL = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
ENDED = {"canceled", "unpaid", "incomplete_expired"}


def apply_plan(db, user: User, plan_key):
    """Set the plan and pause/resume websites so the user is never over their limit."""
    user.plan = plan_key if plan_key in PLANS and plan_key != "free" else None
    from app.core.plans import limit_for
    plan = plan_for(user)
    monitors = db.query(Monitor).filter(Monitor.user_id == user.id).order_by(Monitor.created_at.asc(), Monitor.id.asc()).all()
    # Each kind has its own allowance (websites, servers, scheduled jobs). Within each kind the
    # oldest stay on and the rest pause (never deleted) until the customer upgrades again.
    for kind in ("website", "port", "heartbeat", "api"):
        mine = [m for m in monitors if (m.kind or "website") == kind]
        cap = limit_for(plan, kind)
        for i, m in enumerate(mine):
            m.is_active = i < cap


@router.get("/payments/checkout/{plan}")
def checkout(plan: str, request: Request, billing: str = "month", db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if plan not in PLANS or plan == "free":
        raise HTTPException(status_code=404, detail="That plan doesn't exist.")
    # Already paying? Send them to manage their subscription instead of starting a second one.
    if user.stripe_subscription_id and user.plan:
        return RedirectResponse(url="/api/payments/manage", status_code=302)
    try:
        session = create_checkout_session(
            plan=plan, user=user, billing="year" if billing == "year" else "month",
            success_url=f"{SITE_URL}/dashboard?payment=success",
            cancel_url=f"{SITE_URL}/pricing",
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        print(f"Checkout failed for user {user.id}: {e!r}")
        raise HTTPException(status_code=502, detail="We couldn't open the payment page. Please try again in a minute.")


@router.get("/payments/manage")
def manage_billing(request: Request, db: Session = Depends(get_db)):
    """Stripe's own page to change card, see invoices, switch or cancel the plan."""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not user.stripe_customer_id:
        return RedirectResponse(url="/pricing", status_code=302)
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    try:
        portal = stripe.billing_portal.Session.create(customer=user.stripe_customer_id, return_url=f"{SITE_URL}/account")
        return RedirectResponse(url=portal.url, status_code=303)
    except Exception as e:
        print(f"Billing portal failed for user {user.id}: {e!r}")
        raise HTTPException(status_code=502, detail="We couldn't open billing right now. Please email support and we'll help.")


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        print("STRIPE_WEBHOOK_SECRET is not set; refusing webhook")
        raise HTTPException(status_code=500, detail="Webhook not configured")
    try:
        # Proves the message really came from Stripe, so nobody can fake an upgrade.
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature"), secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    obj = event["data"]["object"]
    kind = event["type"]

    if kind == "checkout.session.completed":
        user = None
        ref = obj.get("client_reference_id")
        if ref and str(ref).isdigit():
            user = db.query(User).filter(User.id == int(ref)).first()
        paid_email = obj.get("customer_email") or (obj.get("customer_details") or {}).get("email")
        if not user and paid_email:
            user = db.query(User).filter(User.email == paid_email).first()
        plan = (obj.get("metadata") or {}).get("plan")
        if user and plan in PLANS:
            user.stripe_customer_id = obj.get("customer") or user.stripe_customer_id
            user.stripe_subscription_id = obj.get("subscription") or user.stripe_subscription_id
            apply_plan(db, user, plan)
            db.commit()
            print(f"Payment successful for user {user.id}: {plan}")

    elif kind in ("customer.subscription.updated", "customer.subscription.deleted"):
        user = db.query(User).filter(User.stripe_customer_id == obj.get("customer")).first()
        if user:
            if kind == "customer.subscription.deleted" or obj.get("status") in ENDED:
                if not user.stripe_subscription_id or user.stripe_subscription_id == obj.get("id"):
                    user.stripe_subscription_id = None
                    apply_plan(db, user, None)
                    print(f"Subscription ended for user {user.id}; moved to Free")
            else:
                plan = (obj.get("metadata") or {}).get("plan")
                if plan in PLANS:
                    apply_plan(db, user, plan)
            db.commit()

    elif kind == "invoice.payment_failed":
        # Stripe retries and emails the customer; if it never succeeds we get subscription.deleted.
        print(f"Payment failed for customer {obj.get('customer')}")

    return {"status": "ok"}
