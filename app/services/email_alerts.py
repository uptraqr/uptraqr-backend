import resend
from datetime import datetime

resend.api_key = "re_S7QuXdQy_Nsyn3NX1AKn8X2LUp7JKYnap"

FROM_EMAIL = "alerts@uptraqr.com"
ALERT_EMAIL = "pathanzaid3746@gmail.com"

def send_down_alert(monitor_name: str, url: str):
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": ALERT_EMAIL,
            "subject": f"🔴 ALERT: {monitor_name} is DOWN",
            "html": f"""
            <h2 style='color: red;'>🔴 Site Down Alert</h2>
            <p><strong>{monitor_name}</strong> is not responding.</p>
            <p><strong>URL:</strong> {url}</p>
            <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            <p>We are monitoring and will notify you when it recovers.</p>
            <br>
            <p>— Uptraqr Monitoring</p>
            """
        })
        print(f"Down alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def send_recovery_alert(monitor_name: str, url: str):
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": ALERT_EMAIL,
            "subject": f"✅ RESOLVED: {monitor_name} is back UP",
            "html": f"""
            <h2 style='color: green;'>✅ Site Recovered</h2>
            <p><strong>{monitor_name}</strong> is back online.</p>
            <p><strong>URL:</strong> {url}</p>
            <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            <br>
            <p>— Uptraqr Monitoring</p>
            """
        })
        print(f"Recovery alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def send_ssl_alert(monitor_name: str, url: str, days_left: int):
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": ALERT_EMAIL,
            "subject": f"⚠️ SSL Warning: {monitor_name} expires in {days_left} days",
            "html": f"""
            <h2 style='color: orange;'>⚠️ SSL Certificate Expiring Soon</h2>
            <p><strong>{monitor_name}</strong> SSL certificate is expiring soon.</p>
            <p><strong>URL:</strong> {url}</p>
            <p><strong>Days Left:</strong> {days_left} days</p>
            <p>Please renew your SSL certificate before it expires.</p>
            <br>
            <p>— Uptraqr Monitoring</p>
            """
        })
        print(f"SSL alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")