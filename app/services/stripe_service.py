import stripe
import os
from dotenv import load_dotenv

load_dotenv()

PLANS = {
    "starter": {
        "name": "Starter",
        "price": 1000,
        "currency": "cad",
        "monitors": 3,
        "interval": "month"
    },
    "pro": {
        "name": "Pro",
        "price": 2500,
        "currency": "cad",
        "monitors": 10,
        "interval": "month"
    },
    "agency": {
        "name": "Agency",
        "price": 6500,
        "currency": "cad",
        "monitors": 999,
        "interval": "month"
    }
}

def create_checkout_session(plan: str, user_email: str, success_url: str, cancel_url: str):
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    
    plan_data = PLANS.get(plan)
    if not plan_data:
        raise ValueError(f"Invalid plan: {plan}")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": plan_data["currency"],
                "product_data": {
                    "name": f"Uptraqr {plan_data['name']} Plan",
                    "description": f"Up to {plan_data['monitors']} monitors"
                },
                "unit_amount": plan_data["price"],
                "recurring": {
                    "interval": plan_data["interval"]
                }
            },
            "quantity": 1
        }],
        mode="subscription",
        customer_email=user_email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"plan": plan, "email": user_email}
    )
    return session