import stripe
import os
from dotenv import load_dotenv

load_dotenv()

PLANS = {
    "starter": {
        "name": "Starter",
        "price": 1000,
        "currency": "cad",
        "monitors": 5,
        "interval": "month"
    },
    "pro": {
        "name": "Pro",
        "price": 2500,
        "currency": "cad",
        "monitors": 15,
        "interval": "month"
    },
    "agency": {
        "name": "Agency",
        "price": 6500,
        "currency": "cad",
        "monitors": 50,
        "interval": "month"
    }
}

def create_checkout_session(plan: str, user, success_url: str, cancel_url: str):
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    plan_data = PLANS.get(plan)
    if not plan_data:
        raise ValueError(f"Invalid plan: {plan}")
    who = {"customer": user.stripe_customer_id} if user.stripe_customer_id else {"customer_email": user.email}
    return stripe.checkout.Session.create(
        **who,
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": plan_data["currency"],
                "product_data": {
                    "name": f"Uptraqr {plan_data['name']} Plan",
                    "description": f"Up to {plan_data['monitors']} websites",
                },
                "unit_amount": plan_data["price"],
                "recurring": {"interval": plan_data["interval"]},
            },
            "quantity": 1,
        }],
        mode="subscription",
        client_reference_id=str(user.id),            # who paid, even if they change their email later
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"plan": plan},
        subscription_data={"metadata": {"plan": plan, "user_id": str(user.id)}},
        allow_promotion_codes=True,
    )
