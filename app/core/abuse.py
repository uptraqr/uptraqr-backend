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


# Cloudflare's published address ranges (cloudflare.com/ips). Only a request that really
# came through Cloudflare may tell us the visitor's address in CF-Connecting-IP; anyone
# else could fake that header to dodge the limits.
import ipaddress as _ip
_CLOUDFLARE = [_ip.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32")]


def _from_cloudflare(addr: str) -> bool:
    try:
        a = _ip.ip_address(addr)
    except ValueError:
        return False
    return any(a in n for n in _CLOUDFLARE)


def client_ip(request) -> str:
    """The visitor's real address, in a way that can't be faked with a header."""
    h = request.headers
    # Railway's front door adds the address that connected to it as the last X-Forwarded-For entry.
    forwarded = [p.strip() for p in (h.get("x-forwarded-for") or "").split(",") if p.strip()]
    peer = h.get("x-real-ip") or (forwarded[-1] if forwarded else None) or (request.client.host if request.client else "unknown")
    cf = h.get("cf-connecting-ip")
    if cf and _from_cloudflare(peer):
        return cf
    try:
        internal = _ip.ip_address(peer).is_private
    except ValueError:
        internal = True
    if internal:
        # We can't see past the hosting proxy here; fall back to what it passed on,
        # so everyone isn't lumped together under one address.
        return cf or (forwarded[0] if forwarded else peer)
    return peer


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
