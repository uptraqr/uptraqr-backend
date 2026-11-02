import resend
import os
from datetime import datetime
import pytz

def get_vancouver_time():
    vancouver_tz = pytz.timezone('America/Vancouver')
    return datetime.now(vancouver_tz).strftime('%Y-%m-%d %H:%M:%S PST')
from dotenv import load_dotenv
load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "alerts@uptraqr.com"
ALERT_EMAIL = "support@uptraqr.com"

SIGNATURE = """
<br><br>
<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
<table style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; border-collapse: collapse;">
  <tr>
    <td style="padding-bottom: 12px;">
      <span style="font-size: 26px; font-weight: 900; color: #38bdf8; letter-spacing: -1px;">up</span><span style="font-size: 26px; font-weight: 900; color: #0f172a; letter-spacing: -1px;">traqr</span>
    </td>
  </tr>
  <tr>
    <td style="border-top: 3px solid #38bdf8; padding-top: 12px;">
      <a href="mailto:support@uptraqr.com" style="font-size: 13px; color: #38bdf8; text-decoration: none; font-weight: 600;">support@uptraqr.com</a>
      <br>
      <a href="https://www.uptraqr.com" style="font-size: 13px; color: #0f172a; text-decoration: none; font-weight: 600;">www.uptraqr.com</a>
      <br><br>
      <span style="font-size: 11px; color: #94a3b8; font-style: italic; letter-spacing: 0.5px;">We watch your website 24/7 so you don't have to.</span>
    </td>
  </tr>
</table>
"""

def _send(params: dict):
    # Drop empty fields (e.g. no bcc) so the email service doesn't reject them
    return resend.Emails.send({k: v for k, v in params.items() if v})

def send_down_alert(monitor_name: str, url: str, to_email: str = None):
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "bcc": ALERT_EMAIL if to_email else None,
            "subject": f"🔴 ALERT: {monitor_name} is DOWN",
            "html": f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #2d0a0a; border-left: 4px solid #ef4444; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #ef4444; margin: 0 0 12px 0;">🔴 Site Down Alert</h2>
                    <p style="color: #e2e8f0; margin: 0;"><strong>{monitor_name}</strong> is not responding.</p>
                </div>
                <table style="width: 100%; border-collapse: collapse; background: #f8fafc; border-radius: 8px; overflow: hidden;">
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; width: 40%; border-bottom: 1px solid #e2e8f0;">Site Name</td>
                        <td style="padding: 12px 16px; color: #0f172a; border-bottom: 1px solid #e2e8f0;">{monitor_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; border-bottom: 1px solid #e2e8f0;">URL</td>
                        <td style="padding: 12px 16px; border-bottom: 1px solid #e2e8f0;"><a href="{url}" style="color: #38bdf8;">{url}</a></td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569;">Time (UTC)</td>
                        <td style="padding: 12px 16px; color: #0f172a;">{get_vancouver_time()}</td>
                    </tr>
                </table>
                <p style="color: #475569; margin-top: 20px; font-size: 14px;">We are actively monitoring and will notify you the moment it recovers.</p>
                {SIGNATURE}
            </div>
            """
        })
        print(f"Down alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def send_recovery_alert(monitor_name: str, url: str, to_email: str = None):
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "bcc": ALERT_EMAIL if to_email else None,
            "subject": f"✅ RESOLVED: {monitor_name} is back UP",
            "html": f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #052e16; border-left: 4px solid #22c55e; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #22c55e; margin: 0 0 12px 0;">✅ Site Recovered</h2>
                    <p style="color: #e2e8f0; margin: 0;"><strong>{monitor_name}</strong> is back online.</p>
                </div>
                <table style="width: 100%; border-collapse: collapse; background: #f8fafc; border-radius: 8px; overflow: hidden;">
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; width: 40%; border-bottom: 1px solid #e2e8f0;">Site Name</td>
                        <td style="padding: 12px 16px; color: #0f172a; border-bottom: 1px solid #e2e8f0;">{monitor_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; border-bottom: 1px solid #e2e8f0;">URL</td>
                        <td style="padding: 12px 16px; border-bottom: 1px solid #e2e8f0;"><a href="{url}" style="color: #38bdf8;">{url}</a></td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569;">Time (UTC)</td>
                        <td style="padding: 12px 16px; color: #0f172a;">{get_vancouver_time()}</td>
                    </tr>
                </table>
                <p style="color: #475569; margin-top: 20px; font-size: 14px;">Your site is back online and we are continuing to monitor it 24/7.</p>
                {SIGNATURE}
            </div>
            """
        })
        print(f"Recovery alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def send_ssl_alert(monitor_name: str, url: str, days_left: int, to_email: str = None):
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "bcc": ALERT_EMAIL if to_email else None,
            "subject": f"⚠️ SSL Warning: {monitor_name} expires in {days_left} days",
            "html": f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #2d1f00; border-left: 4px solid #f59e0b; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="color: #f59e0b; margin: 0 0 12px 0;">⚠️ SSL Certificate Expiring Soon</h2>
                    <p style="color: #e2e8f0; margin: 0;"><strong>{monitor_name}</strong> SSL certificate is expiring in <strong>{days_left} days</strong>.</p>
                </div>
                <table style="width: 100%; border-collapse: collapse; background: #f8fafc; border-radius: 8px; overflow: hidden;">
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; width: 40%; border-bottom: 1px solid #e2e8f0;">Site Name</td>
                        <td style="padding: 12px 16px; color: #0f172a; border-bottom: 1px solid #e2e8f0;">{monitor_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569; border-bottom: 1px solid #e2e8f0;">URL</td>
                        <td style="padding: 12px 16px; border-bottom: 1px solid #e2e8f0;"><a href="{url}" style="color: #38bdf8;">{url}</a></td>
                    </tr>
                    <tr>
                        <td style="padding: 12px 16px; font-weight: 600; color: #475569;">Days Left</td>
                        <td style="padding: 12px 16px; color: #f59e0b; font-weight: 700;">{days_left} days</td>
                    </tr>
                </table>
                <p style="color: #475569; margin-top: 20px; font-size: 14px;">Please renew your SSL certificate before it expires to avoid security warnings for your visitors.</p>
                {SIGNATURE}
            </div>
            """
        })
        print(f"SSL alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")
