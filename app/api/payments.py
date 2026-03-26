from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import User
from app.services.stripe_service import create_checkout_session
import stripe
import os

router = APIRouter()

@router.get("/payments/checkout/{plan}")
def checkout(plan: str, request: Request, db: Session = Depends(get_db)):
    from app.core.auth import get_current_user_optional
    current_user = get_current_user_optional(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    try:
        session = create_checkout_session(
            plan=plan,
            user_email=current_user.email,
            success_url="https://www.uptraqr.com/dashboard?payment=success",
            cancel_url="https://www.uptraqr.com/pricing"
        )
        return RedirectResponse(url=session.url, status_code=302)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")
        plan = session.get("metadata", {}).get("plan")

        user = db.query(User).filter(User.email == email).first()
        if user:
            user.plan = plan
            user.is_active = True
            db.commit()
            print(f"✅ Payment successful for {email} - Plan: {plan}")

    elif event["type"] == "customer.subscription.deleted":
        email = event["data"]["object"].get("customer_email")
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.plan = None
            db.commit()
            print(f"❌ Subscription cancelled for {email}")

    elif event["type"] == "invoice.payment_failed":
        email = event["data"]["object"].get("customer_email")
        print(f"⚠️ Payment failed for {email}")

    return {"status": "ok"}