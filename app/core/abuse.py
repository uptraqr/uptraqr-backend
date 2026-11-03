"""
Protections against people creating many free accounts.

None of these is perfect on its own; together they make farming free accounts
more effort than paying for a plan.
"""
import time
from urllib.parse import urlparse

# Common throwaway-inbox services. Not exhaustive, but catches the usual ones.
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "20minutemail.com", "33mail.com", "anonaddy.me",
    "burnermail.io", "discard.email", "dispostable.com", "dropmail.me", "emailondeck.com",
    "fakeinbox.com", "getairmail.com", "getnada.com", "guerrillamail.com", "guerrillamail.net",
    "guerrillamail.org", "guerrillamailblock.com", "harakirimail.com", "inboxkitten.com",
    "maildrop.cc", "mailcatch.com", "mailinator.com", "mailinator.net", "mailnesia.com",
    "mailpoof.com", "mintemail.com", "moakt.com", "mohmal.com", "mytemp.email", "nada.email",
    "sharklasers.com", "spamgourmet.com", "temp-mail.io", "temp-mail.org", "tempail.com",
    "tempmail.com", "tempmail.dev", "tempmail.net", "tempmailo.com", "tempr.email",
    "throwawaymail.com", "trashmail.com", "trashmail.de", "yopmail.com", "yopmail.fr",
    "yopmail.net", "emailfake.com", "fakemail.net", "mail.tm", "tmpmail.org", "tmpmail.net",
    "spambox.us", "mailsac.com", "linshiyouxiang.net", "byom.de", "crazymailing.com",
}
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def canonical_email(email: str) -> str:
    """
    The real inbox an address delivers to, used only to spot duplicates.
    zaid+1@gmail.com, z.aid@gmail.com and ZAID@googlemail.com all become zaid@gmail.com.
    For other providers, only the "+anything" part is removed.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def is_disposable(email: str) -> bool:
    domain = (email or "").strip().lower().rsplit("@", 1)[-1]
    return domain in DISPOSABLE_DOMAINS or any(domain.endswith("." + d) for d in DISPOSABLE_DOMAINS)


def client_ip(request) -> str:
    """The visitor's real address. Cloudflare passes it in CF-Connecting-IP."""
    h = request.headers
    ip = h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else "unknown")


class RateLimiter:
    """Allows `limit` events per `window` seconds for each key (kept in memory)."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window, self.hits = limit, window, {}

    def allow(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self.hits.get(key, []) if now - t < self.window]
        if len(recent) >= self.limit:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        # keep memory small
        if len(self.hits) > 10000:
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
        return True


signup_limiter = RateLimiter(limit=3, window=24 * 3600)   # 3 new accounts per connection per day


def site_key(url: str) -> str:
    """shop.example.com and www.shop.example.com count as the same website."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host
