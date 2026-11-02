import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

def send_sms(to_number: str, message: str):
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_number]):
            print("Twilio credentials not configured")
            return False

        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"SMS sent: {message.sid}")
        return True
    except Exception as e:
        print(f"SMS failed: {e}")
        return False

def send_down_sms(monitor_name: str, url: str, to_number: str):
    message = f"🔴 ALERT: {monitor_name} is DOWN!\nURL: {url}\nUptraqr is monitoring and will notify you when it recovers."
    return send_sms(to_number, message)

def send_recovery_sms(monitor_name: str, url: str, to_number: str):
    message = f"✅ RECOVERED: {monitor_name} is back UP!\nURL: {url}\nYour site is back online."
    return send_sms(to_number, message)

def send_ssl_sms(monitor_name: str, url: str, days_left: int, to_number: str):
    message = f"⚠️ SSL WARNING: {monitor_name} SSL expires in {days_left} days!\nURL: {url}\nPlease renew your SSL certificate."
    return send_sms(to_number, message)

def send_defacement_sms(monitor_name: str, url: str, to_number: str):
    message = (f"🚨 UPTRAQR: {monitor_name} shows signs of a possible hack.\nURL: {url}\n"
               "Check your email or dashboard for details.")
    return send_sms(to_number, message)
