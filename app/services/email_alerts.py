import resend
import os
from html import escape
from datetime import datetime

from app.core.timefmt import fmt as _fmt_time
from dotenv import load_dotenv
load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")

# Who alerts come from (must be on a domain verified in Resend).
FROM_EMAIL = os.getenv("FROM_EMAIL", "Uptraqr Alerts <alerts@uptraqr.com>")
# The contact address shown to customers.
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@uptraqr.com")
# Optional: where UpTraQR sends you a hidden copy of every customer alert.
# Leave unset to send no copies.
ADMIN_COPY_EMAIL = os.getenv("ADMIN_COPY_EMAIL") or None
# Used only when an alert has no customer address (shouldn't normally happen).
ALERT_EMAIL = ADMIN_COPY_EMAIL or SUPPORT_EMAIL

_SITE = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
# Same look as the team's Gmail signatures: logo, green line, contact, tagline, free check link.
SIGNATURE = f"""
<table cellpadding="0" cellspacing="0" border="0" style="margin-top:28px;font-family:Arial,Helvetica,sans-serif;color:#0F1B2D;border-collapse:collapse">
  <tr><td style="padding:0 0 8px 0"><a href="{_SITE}" style="text-decoration:none"><img src="{_SITE}/static/email-logo.png" width="154" height="49" alt="Uptraqr" style="display:block;border:0;width:154px;height:49px"></a></td></tr>
  <tr><td style="border-top:2px solid #16A34A;padding:10px 0 0 0;font-size:14px;line-height:20px">
    <b style="font-size:15px;color:#0F1B2D">Uptraqr Support</b><br>
    <a href="mailto:{SUPPORT_EMAIL}" style="color:#0F1B2D;text-decoration:none">{SUPPORT_EMAIL}</a> &nbsp;&middot;&nbsp; <a href="{_SITE}" style="color:#0F1B2D;text-decoration:none">www.uptraqr.com</a><br>
    <span style="color:#64748B;font-size:12px">Uptraq Technologies &middot; Surrey, BC, Canada</span>
  </td></tr>
  <tr><td style="padding:10px 0 0 0;font-size:12px;line-height:18px;color:#64748B;font-style:italic">We watch your website 24/7 so you don't have to. <a href="{_SITE}/check" style="color:#16A34A;font-style:normal;font-weight:bold;text-decoration:none">Free website check &rarr;</a></td></tr>
</table>
"""

def unsubscribe_link(email: str, kind: str) -> str:
    """A signed link that turns off one kind of email ('alerts' or 'reports') for this address."""
    from app.core.auth import create_link_token
    site = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
    return f"{site}/unsubscribe?token={create_link_token(email, 'unsubscribe', 60 * 24 * 365, kind=kind)}"


_UNSUB_TEXT = {
    "alerts": "You're getting this because you asked Uptraqr to watch this website.",
    "reports": "You're getting this monthly report as part of your Uptraqr plan.",
}


def _send(params: dict, unsubscribe: str = None):
    """
    Send through Resend. For alerts and reports, add a visible unsubscribe link
    and the standard one-click unsubscribe headers that Gmail and Outlook show.
    """
    to = params.get("to")
    if unsubscribe and to and to != ALERT_EMAIL:
        link = unsubscribe_link(to, unsubscribe)
        params["html"] = (params.get("html") or "") + (
            f'''<p style="font-family:-apple-system,'Segoe UI',sans-serif;color:#94a3b8;font-size:12px;max-width:600px;margin:12px auto 0;padding:0 20px">
            {_UNSUB_TEXT[unsubscribe]} <a href="{escape(link)}" style="color:#64748b">Turn off these emails</a>.</p>''')
        params["headers"] = {"List-Unsubscribe": f"<{link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    # Drop empty fields (e.g. no bcc) so the email service doesn't reject them
    return resend.Emails.send({k: v for k, v in params.items() if v})

def describe_monitor(monitor):
    """(what it is, where it is) in plain words, for emails."""
    kind = getattr(monitor, "kind", None) or "website"
    if kind == "port":
        return "server", f"{monitor.url} (port {monitor.port})"
    if kind == "api":
        return "API", f"{monitor.api_method or 'GET'} {monitor.url}"
    if kind == "heartbeat":
        every = monitor.heartbeat_minutes or 60
        nice = (f"{every // 1440} day{'s' if every // 1440 != 1 else ''}" if every >= 1440 and every % 1440 == 0
                else f"{every // 60} hour{'s' if every // 60 != 1 else ''}" if every >= 60 and every % 60 == 0
                else f"{every} minutes")
        return "scheduled job", f"Checks in every {nice}"
    return "website", monitor.url


def _status_email(colour, bg, line, heading, lead, rows, footer):
    cells = "".join(
        f'''<tr><td style="padding:12px 16px;font-weight:600;color:#475569;width:38%;border-bottom:1px solid #e2e8f0">{escape(k)}</td>
        <td style="padding:12px 16px;color:#0f172a;border-bottom:1px solid #e2e8f0">{v}</td></tr>''' for k, v in rows)
    return f'''
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#0f172a">
      <div style="background:{bg};border:1px solid {line};border-left:4px solid {colour};padding:18px 20px;border-radius:8px;margin-bottom:18px">
        <h2 style="color:{colour};margin:0 0 8px 0;font-size:20px">{heading}</h2>
        <p style="color:#0f172a;margin:0">{lead}</p>
      </div>
      <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px;overflow:hidden">{cells}</table>
      <p style="color:#475569;margin-top:18px;font-size:14px">{footer}</p>
      {SIGNATURE}
    </div>'''


def send_down_alert(monitor_name: str, url: str, to_email: str = None, tz: str = None, monitor=None, reason: str = None, detail: str = None):
    what, where = describe_monitor(monitor) if monitor else ("website", url)
    name = escape(monitor_name)
    if what == "website" and reason == "keyword":
        place = f'<a href="{escape(where)}" style="color:#0F1B2D">{escape(where)}</a>'
        lead = (f"<strong>{name}</strong> is loading, but the words <strong>\u201c{escape(monitor.keyword)}\u201d</strong> "
                "are missing from the page. Something on it may be broken.")
        footer = "We checked twice to be sure. We'll email you as soon as the words are back."
    elif what == "website":
        place = f'<a href="{escape(where)}" style="color:#0F1B2D">{escape(where)}</a>'
        lead, footer = f"<strong>{name}</strong> is not responding.", "We'll keep checking and email you the moment it's back."
    elif what == "API":
        place = escape(where)
        lead = {
            "status": f"<strong>{name}</strong> answered with the wrong status: {escape(detail or '')}.",
            "slow": f"<strong>{name}</strong> is answering too slowly: {escape(detail or '')}.",
            "content": f"<strong>{name}</strong> answered, but the reply no longer contains <strong>\u201c{escape(detail or '')}\u201d</strong>.",
        }.get(reason, f"<strong>{name}</strong> isn't answering.")
        footer = "We checked twice to be sure. We'll email you as soon as it's working normally again."
    elif what == "server":
        place = escape(where)
        lead = f"<strong>{name}</strong> stopped answering on port {monitor.port}."
        footer = "We checked twice to be sure. We'll email you the moment it answers again."
    else:
        place = escape(where)
        last = _fmt_time(monitor.last_ping_at, tz) if monitor.last_ping_at else "never"
        lead = f"<strong>{name}</strong> didn't check in when expected. It may have stopped running."
        footer = f"Its last check-in was {escape(last)}. We'll email you when it checks in again."
    try:
        _send({
            "from": FROM_EMAIL, "to": to_email or ALERT_EMAIL, "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
            "subject": (f"🔴 {monitor_name} missed its check-in" if what == "scheduled job"
                        else f"🟠 {monitor_name}: page content missing" if reason == "keyword"
                        else f"🟠 {monitor_name} is slow" if reason == "slow"
                        else f"🔴 {monitor_name} has a problem" if reason in ("status", "content")
                        else f"🔴 {monitor_name} is down"),
            "html": _status_email("#BF2433", "#FDE7E9", "#F1A7AF",
                                  "🔴 Missed check-in" if what == "scheduled job" else ("🔴 API problem" if what == "API" else f"🔴 {what.capitalize()} down"),
                                  lead, [("Name", name), ("Website" if what == "website" else ("Address" if what == "API" else "Details"), place),
                                         ("Time", escape(_fmt_time(tz=tz)))], footer),
        }, unsubscribe="alerts")
        print(f"Down alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


def send_recovery_alert(monitor_name: str, url: str, to_email: str = None, tz: str = None, monitor=None):
    what, where = describe_monitor(monitor) if monitor else ("website", url)
    name = escape(monitor_name)
    place = f'<a href="{escape(where)}" style="color:#0F1B2D">{escape(where)}</a>' if what == "website" else escape(where)
    lead = (f"<strong>{name}</strong> checked in again." if what == "scheduled job"
            else f"<strong>{name}</strong> is back online.")
    try:
        _send({
            "from": FROM_EMAIL, "to": to_email or ALERT_EMAIL, "reply_to": SUPPORT_EMAIL,
            "bcc": ADMIN_COPY_EMAIL if to_email else None,
            "subject": f"✅ {monitor_name} is back" if what != "scheduled job" else f"✅ {monitor_name} checked in again",
            "html": _status_email("#0B7A52", "#E2F5EC", "#9FD9BE", "✅ All clear", lead,
                                  [("Name", name), ("Website" if what == "website" else "Details", place),
                                   ("Time", escape(_fmt_time(tz=tz)))],
                                  "Everything's working again. We're still watching, day and night."),
        }, unsubscribe="alerts")
        print(f"Recovery alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


def send_domain_alert(monitor_name: str, domain: str, days_left: int, expiry, to_email: str, tz: str = None):
    """Reminder that the domain name itself is about to expire (website AND email stop working)."""
    when = "today" if days_left <= 0 else ("tomorrow" if days_left == 1 else f"in {days_left} days")
    try:
        _send({
            "from": FROM_EMAIL, "to": to_email, "reply_to": SUPPORT_EMAIL,
            "subject": f"⚠️ Your domain {domain} expires {when}",
            "html": _status_email("#9A5800", "#FFF1D6", "#F0C985", "⚠️ Domain name expiring",
                                  f"Your domain <strong>{escape(domain)}</strong> expires {when}.",
                                  [("Website", escape(monitor_name)), ("Domain", escape(domain)),
                                   ("Expires", escape(_fmt_time(expiry, tz)))],
                                  "If it runs out, your website <strong>and</strong> any email addresses on it stop working, "
                                  "and someone else could register it. Renew it with the company you bought it from "
                                  "(for example GoDaddy, Namecheap or your web host), or turn on auto-renew there."),
        }, unsubscribe="alerts")
        print(f"Domain alert sent for {domain}")
    except Exception as e:
        print(f"Failed to send domain alert: {e}")


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
                        <td style="padding: 12px 16px; border-bottom: 1px solid #e2e8f0;"><a href="{url}" style="color: #0F1B2D;">{url}</a></td>
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
        }, unsubscribe="alerts")
        print(f"SSL alert sent for {monitor_name}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


SEVERITY_LABEL = {"high": "🚨 Hacker sign", "medium": "⚠️ Change", "low": "ℹ️ Minor change"}

def send_defacement_alert(monitor_name: str, url: str, status: str, findings: list, to_email: str = None, tz: str = None):
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
                <p style="color:#e2e8f0;margin:0;"><strong>{name}</strong> — <a href="{safe_url}" style="color:#A7F3D0;">{safe_url}</a></p>
              </div>
              <p style="color:#334155;">{lead}</p>
              <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px;overflow:hidden;">{rows}</table>
              <p style="color:#475569;margin-top:20px;font-size:14px;"><strong>What to do:</strong><br>
              • If you made this change: open your Uptraqr dashboard and press <em>"Yes, I made this change"</em>.<br>
              • If you didn't: contact whoever runs your website or hosting right away, change your website passwords, and restore a backup.</p>
              <p style="color:#94a3b8;font-size:13px;">Detected {_fmt_time(tz=tz)}</p>
              {SIGNATURE}
            </div>'''
        }, unsubscribe="alerts")
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
                <p style="color:#e2e8f0;margin:0;"><strong>{name}</strong> (<a href="{safe_url}" style="color:#A7F3D0;">{safe_url}</a>) matches its known-good version again.</p>
              </div>
              {SIGNATURE}
            </div>'''
        }, unsubscribe="alerts")
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
            "subject": "Confirm your email to start using Uptraqr",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#0f172a;">
              <h2 style="margin:0 0 12px 0;">Confirm your email</h2>
              <p style="color:#334155;">Hi {safe_name}, thanks for signing up. Tap the button below to confirm this is your email address. This is where we'll send your website alerts.</p>
              <p style="margin:28px 0;"><a href="{safe_link}" style="background:#0F1B2D;color:#FFFFFF;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;">Confirm my email</a></p>
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
              <p style="margin:24px 0"><a href="{escape(action_link)}" style="background:#0F1B2D;color:#FFFFFF;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">{button}</a></p>
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
              <p style="margin:24px 0"><a href="{escape(link)}" style="background:#0F1B2D;color:#FFFFFF;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">Log me in</a></p>
              <p style="color:#64748b;font-size:14px">The link works for 30 minutes. If you didn't ask to log in, ignore this email; your account is safe.</p>
              {SIGNATURE}
            </div>'''
        })
        return True
    except Exception as e:
        print(f"Failed to send login link: {e}")
        return False


def send_monthly_report_email(to_email: str, month_label: str, sites: list) -> bool:
    """
    Monthly summary for paid plans. Each site: name, url, uptime (float or None),
    incidents (int), grade (str or None), tamper (str), ssl_days (int or None).
    """
    rows = ""
    for s in sites:
        up = "No data" if s["uptime"] is None else f'{s["uptime"]:.2f}%'
        up_colour = "#64748b" if s["uptime"] is None else ("#0B7A52" if s["uptime"] >= 99.5 else "#9A5800" if s["uptime"] >= 98 else "#BF2433")
        outages = "No outages" if not s["incidents"] else f'{s["incidents"]} outage{"s" if s["incidents"] != 1 else ""}'
        ssl = ("No SSL" if s["ssl_days"] is None else "SSL expired" if s["ssl_days"] < 0
               else f'SSL renews in {s["ssl_days"]} days')
        grade_txt = s["grade"] or "?"
        rows += f'''
        <tr><td style="padding:14px;border-bottom:1px solid #e2e8f0">
          <strong style="color:#0f172a">{escape(s["name"])}</strong><br>
          <span style="color:#64748b;font-size:13px">{escape(s["url"])}</span><br>
          <span style="font-size:14px;color:#334155">Online <strong style="color:{up_colour}">{up}</strong> · {outages} · {escape(s["tamper"])} · {ssl}</span>
        </td><td style="padding:14px;border-bottom:1px solid #e2e8f0;text-align:right;vertical-align:top">
          <span style="font-size:13px;color:#64748b">Health</span><br>
          <strong style="font-size:22px;color:{_GRADE_COLOURS.get(grade_txt, "#64748b")}">{grade_txt}</strong>
        </td></tr>'''
    site = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
    try:
        _send({
            "from": FROM_EMAIL,
            "to": to_email,
            "reply_to": SUPPORT_EMAIL,
            "subject": f"Your websites in {month_label}",
            "html": f'''
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#0f172a;">
              <h2 style="margin:0 0 6px 0;">Your monthly website report</h2>
              <p style="margin:0 0 18px 0;color:#475569;">How your websites did in {escape(month_label)}.</p>
              <table style="width:100%;border-collapse:collapse;background:#f8fafc;border-radius:8px;overflow:hidden;margin-bottom:20px">{rows}</table>
              <p style="color:#334155">The health grade covers security settings, signs of hacking, speed, Google basics and email setup.
              Open your dashboard to see the details and how to fix anything.</p>
              <p style="margin:24px 0"><a href="{site}/dashboard" style="background:#0F1B2D;color:#FFFFFF;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">Open my dashboard</a></p>
              {SIGNATURE}
            </div>'''
        }, unsubscribe="reports")
        return True
    except Exception as e:
        print(f"Failed to send monthly report: {e}")
        return False


def _plain_email(heading: str, paras: list, button_text: str, button_link: str) -> str:
    body = "".join(f'<p style="color:#334155;margin:0 0 14px 0">{p}</p>' for p in paras)
    return f'''
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#0f172a">
      <h2 style="margin:0 0 14px 0">{heading}</h2>
      {body}
      <p style="margin:22px 0"><a href="{escape(button_link)}" style="background:#0F1B2D;color:#FFFFFF;padding:14px 22px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">{button_text}</a></p>
      {SIGNATURE}
    </div>'''


def send_trial_reminder_email(to_email: str, days_left: int) -> bool:
    site = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
    when = "tomorrow" if days_left <= 1 else f"in {days_left} days"
    try:
        _send({
            "from": FROM_EMAIL, "to": to_email, "reply_to": SUPPORT_EMAIL,
            "subject": f"Your Uptraqr Pro trial ends {when}",
            "html": _plain_email(
                f"Your free Pro trial ends {when}",
                ["Thanks for trying Uptraqr. After your trial, your account moves to the Free plan: one website, "
                 "checked every 5 minutes, with email alerts and SSL and domain reminders.",
                 "Tamper watch, history, server and scheduled job checks, and the monthly report will pause. "
                 "Nothing is deleted, and it all switches back on if you choose a plan.",
                 "Plans start at $10 a month. You can cancel any time."],
                "Choose a plan", f"{site}/pricing"),
        })
        return True
    except Exception as e:
        print(f"Failed to send trial reminder: {e}")
        return False


def send_trial_ended_email(to_email: str, paused: int) -> bool:
    site = os.getenv("SITE_URL", "https://www.uptraqr.com").rstrip("/")
    paused_line = (f"We've paused {paused} of your checks to fit the Free plan. They're saved, not deleted."
                   if paused else "Your website is still being checked on the Free plan.")
    try:
        _send({
            "from": FROM_EMAIL, "to": to_email, "reply_to": SUPPORT_EMAIL,
            "subject": "Your Uptraqr Pro trial has ended",
            "html": _plain_email(
                "Your free Pro trial has ended",
                ["Your account is now on the Free plan. We'll keep checking your website and email you if it goes down "
                 "or its padlock or domain is about to expire.",
                 paused_line,
                 "Want tamper watch and history back? Choose a plan and everything switches on again straight away."],
                "See plans", f"{site}/pricing"),
        })
        return True
    except Exception as e:
        print(f"Failed to send trial ended email: {e}")
        return False
