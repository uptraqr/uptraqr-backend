import resend
import os
from html import escape
from datetime import datetime
import pytz

def get_vancouver_time():
    vancouver_tz = pytz.timezone('America/Vancouver')
    return datetime.now(vancouver_tz).strftime('%Y-%m-%d %H:%M:%S PST')
from dotenv import load_dotenv
load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")

# Who alerts come from (must be on a domain verified in Resend).
FROM_EMAIL = os.getenv("FROM_EMAIL", "UpTraQR Alerts <alerts@uptraqr.com>")
# The contact address shown to customers.
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
# Optional: where UpTraQR sends you a hidden copy of every customer alert.
# Leave unset to send no copies.
ADMIN_COPY_EMAIL = os.getenv("ADMIN_COPY_EMAIL") or None
# Used only when an alert has no customer address (shouldn't normally happen).
ALERT_EMAIL = ADMIN_COPY_EMAIL or SUPPORT_EMAIL

SIGNATURE = f"""
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
      <a href="mailto:{SUPPORT_EMAIL}" style="font-size: 13px; color: #38bdf8; text-decoration: none; font-weight: 600;">{SUPPORT_EMAIL}</a>
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
    monitor_name, url = escape(monitor_name), escape(url)
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
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
    monitor_name, url = escape(monitor_name), escape(url)
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
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
    monitor_name, url = escape(monitor_name), escape(url)
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
            "subject": (f"🔴 SSL certificate for {monitor_name} expires today" if days_left <= 0
                        else f"⚠️ SSL certificate for {monitor_name} expires in {days_left} day{'s' if days_left != 1 else ''}"),
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


SEVERITY_LABEL = {"high": "🚨 Hacker sign", "medium": "⚠️ Change", "low": "ℹ️ Minor change"}

def send_defacement_alert(monitor_name: str, url: str, status: str, findings: list, to_email: str = None):
    name, safe_url = escape(monitor_name), escape(url)
    if status == "suspicious":
        subject = f"🚨 Possible hack: {monitor_name} has signs of an attack"
        colour, bg, heading = "#ef4444", "#2d0a0a", "🚨 Possible website hack detected"
        lead = "We found signs that someone may have tampered with your website. Please check it now."
    else:
        subject = f"⚠️ {monitor_name} changed — was this you?"
        colour, bg, heading = "#f59e0b", "#2d1f00", "⚠️ Your website changed"
        lead = "Important parts of your page changed. If you or your web designer made this change, you can ignore this."
    rows = "".join(
        f'''<tr><td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-weight:600;color:#475569;width:30%">{SEVERITY_LABEL.get(f["severity"], "")}</td>
        <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;color:#0f172a">{escape(f["message"])}
        {f'<br><span style="color:#64748b;font-size:13px">{escape(f["evidence"])}</span>' if f.get("evidence") else ""}</td></tr>'''
        for f in findings if f["severity"] in ("high", "medium")
    )
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
            "subject": subject,
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:20px;">
              <div style="background:{bg};border-left:4px solid {colour};padding:20px;border-radius:8px;margin-bottom:20px;">
                <h2 style="color:{colour};margin:0 0 12px 0;">{heading}</h2>
                <p style="color:#e2e8f0;margin:0;"><strong>{name}</strong> — <a href="{safe_url}" style="color:#38bdf8;">{safe_url}</a></p>
              </div>
              <p style="color:#334155;">{lead}</p>
              <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px;overflow:hidden;">{rows}</table>
              <p style="color:#475569;margin-top:20px;font-size:14px;"><strong>What to do:</strong><br>
              • If you made this change: open your UpTraQR dashboard and press <em>"Yes, I made this change"</em>.<br>
              • If you didn't: contact whoever runs your website or hosting right away, change your website passwords, and restore a backup.</p>
              <p style="color:#94a3b8;font-size:13px;">Detected {get_vancouver_time()}</p>
              {SIGNATURE}
            </div>'''
        })
        print(f"Defacement alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send defacement alert: {e}")


def send_defacement_cleared_alert(monitor_name: str, url: str, to_email: str = None):
    name, safe_url = escape(monitor_name), escape(url)
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email or ALERT_EMAIL,
            "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
            "subject": f"✅ {monitor_name} looks normal again",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:20px;">
              <div style="background:#052e16;border-left:4px solid #22c55e;padding:20px;border-radius:8px;">
                <h2 style="color:#22c55e;margin:0 0 12px 0;">✅ Back to normal</h2>
                <p style="color:#e2e8f0;margin:0;"><strong>{name}</strong> (<a href="{safe_url}" style="color:#38bdf8;">{safe_url}</a>) matches its known-good version again.</p>
              </div>
              {SIGNATURE}
            </div>'''
        })
    except Exception as e:
        print(f"Failed to send defacement cleared alert: {e}")


def send_verification_email(to_email: str, name: str, link: str) -> bool:
    """The 'confirm your email' message sent after signup. Returns True if handed to Resend."""
    safe_name, safe_link = escape(name or "there"), escape(link)
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email,
            "reply_to": SUPPORT_EMAIL,
            "subject": "Confirm your email to start using UpTraQR",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#0f172a;">
              <h2 style="margin:0 0 12px 0;">Confirm your email</h2>
              <p style="color:#334155;">Hi {safe_name}, thanks for signing up. Tap the button below to confirm this is your email address. This is where we'll send your website alerts.</p>
              <p style="margin:28px 0;"><a href="{safe_link}" style="background:#5CC8FF;color:#06213A;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;">Confirm my email</a></p>
              <p style="color:#64748b;font-size:14px;">The link works for 24 hours. If the button doesn't work, copy this address into your browser:<br><span style="word-break:break-all;">{safe_link}</span></p>
              <p style="color:#64748b;font-size:14px;">Didn't sign up? You can ignore this email and no account will be activated.</p>
              {SIGNATURE}
            </div>'''
        })
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False


_GRADE_COLOURS = {"A": "#16a34a", "B": "#16a34a", "C": "#d97706", "D": "#dc2626", "F": "#dc2626", "?": "#64748b"}


def send_report_email(to_email: str, report: dict, action_link: str, report_link: str, new_account: bool) -> bool:
    """The website health report, with one button to turn on monitoring (or log in)."""
    host = escape(report["host"])
    g = report["grade"]
    cats = "".join(
        f'''<tr><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#334155">{escape(c["name"])}</td>
        <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-weight:700;color:{_GRADE_COLOURS.get(c["grade"], "#64748b")};text-align:right">{c["grade"]}</td></tr>'''
        for c in report["categories"])
    fixes = "".join(
        f'''<li style="margin:0 0 12px 0"><strong>{escape(f["detail"])}</strong><br><span style="color:#475569">{escape(f["fix"] or "")}</span></li>'''
        for f in report["fixes"][:3])
    hacked = ('''<p style="background:#fef2f2;border-left:4px solid #dc2626;padding:12px 14px;color:#7f1d1d"><strong>Possible signs of hacking.</strong>
        Please check your website today and contact your web designer or host.</p>''' if report.get("hacked") else "")
    button = "Turn on free alerts for " + host if new_account else "Log in to Uptraqr"
    explain = (f"Tap below and we'll start watching {host} for you, free. We'll email you if it goes down or its security certificate is about to expire."
               if new_account else "You already have an Uptraqr account with this email. Tap below to log in; we'll add this website if your plan has room.")
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email,
            "reply_to": SUPPORT_EMAIL,
            "subject": f"Your website health report for {report['host']}: grade {g}",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#0f172a;">
              <h2 style="margin:0 0 6px 0;">{host}</h2>
              <p style="margin:0 0 18px 0;color:#475569;">Overall grade <strong style="color:{_GRADE_COLOURS.get(g, "#64748b")};font-size:20px">{g}</strong> ({report["score"]} out of 100)</p>
              {hacked}
              <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px;overflow:hidden;margin-bottom:20px">{cats}</table>
              {"<h3 style='margin:0 0 10px 0'>Top things to fix</h3><ol style='padding-left:20px;margin:0 0 20px 0'>" + fixes + "</ol>" if fixes else "<p>Nice work, we didn't find anything important to fix.</p>"}
              <p style="color:#334155">{explain}</p>
              <p style="margin:24px 0"><a href="{escape(action_link)}" style="background:#5CC8FF;color:#06213A;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">{button}</a></p>
              <p style="color:#64748b;font-size:14px">See every check and how to fix it: <a href="{escape(report_link)}" style="color:#0284c7">full report</a>. The button works for 24 hours.</p>
              <p style="color:#94a3b8;font-size:13px">You're getting this because someone asked for this report on uptraqr.com using your email. If that wasn't you, ignore this email and nothing will be set up.</p>
              {SIGNATURE}
            </div>'''
        })
        return True
    except Exception as e:
        print(f"Failed to send report email: {e}")
        return False


def send_login_link_email(to_email: str, link: str) -> bool:
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email,
            "reply_to": SUPPORT_EMAIL,
            "subject": "Your Uptraqr login link",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#0f172a;">
              <h2 style="margin:0 0 12px 0;">Log in to Uptraqr</h2>
              <p style="color:#334155;">Tap the button to log in. No password needed.</p>
              <p style="margin:24px 0"><a href="{escape(link)}" style="background:#5CC8FF;color:#06213A;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">Log me in</a></p>
              <p style="color:#64748b;font-size:14px">The link works for 30 minutes. If you didn't ask to log in, ignore this email; your account is safe.</p>
              {SIGNATURE}
            </div>'''
        })
        return True
    except Exception as e:
        print(f"Failed to send login link: {e}")
        return False
