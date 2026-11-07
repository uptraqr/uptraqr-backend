"""
Safe page fetching for monitoring.

Customers type in any web address they like. Without these checks, someone
could add an address like http://169.254.169.254/ or http://localhost:8080/
and trick UpTraQR into reading its own private network (an attack called
SSRF). Every address — including every redirect — is checked against this
list before we connect.
"""
import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import requests

USER_AGENT = "UptraqrBot/1.0 (+https://www.uptraqr.com)"
MAX_BYTES = 2_000_000          # stop reading pages bigger than ~2 MB
TIMEOUT = 15                   # seconds
MAX_REDIRECTS = 5

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".railway.internal")


class UnsafeURLError(ValueError):
    """The address points somewhere we must never connect to."""


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def check_url_is_safe(url: str) -> str:
    """Raise UnsafeURLError unless url is http(s) to a public internet host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http:// and https:// addresses can be monitored.")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeURLError("That address has no website name in it.")
    if parsed.username or parsed.password:
        raise UnsafeURLError("Addresses with a username or password in them can't be monitored.")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError("That address points to a private network.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise UnsafeURLError("We couldn't find that website. Check the address for typos.")
    for info in infos:
        if not _ip_is_public(info[4][0]):
            raise UnsafeURLError("That address points to a private network.")
    return url


def safe_get_detailed(url: str, max_bytes: int = MAX_BYTES):
    """
    Fetch a page, checking every hop against the private-network rules.
    Returns a dict: final_url, status, text, headers (of the final page),
    seconds (total time), hops (list of URLs visited), bytes.
    Raises UnsafeURLError or requests.RequestException.
    """
    import time as _t
    start = _t.monotonic()
    current, hops = url, []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    for _ in range(MAX_REDIRECTS + 1):
        check_url_is_safe(current)
        hops.append(current)
        resp = session.get(current, timeout=TIMEOUT, allow_redirects=False, stream=True)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                break
            current = urljoin(current, location)
            continue
        chunks, total = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        resp.close()
        encoding = resp.encoding or "utf-8"
        return {
            "final_url": current,
            "status": resp.status_code,
            "text": b"".join(chunks).decode(encoding, errors="replace"),
            "headers": {k.lower(): v for k, v in resp.headers.items()},
            "seconds": round(_t.monotonic() - start, 2),
            "hops": hops,
            "bytes": total,
        }
    raise requests.TooManyRedirects("Too many redirects")


def safe_get(url: str):
    """Fetch a page, checking every hop. Returns (final_url, status_code, html_text)."""
    r = safe_get_detailed(url)
    return r["final_url"], r["status"], r["text"]


def check_host_is_safe(host: str, port: int) -> str:
    """For port checks: the public IP address to connect to, or UnsafeURLError."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or len(host) > 253 or any(c in host for c in "/@: "):
        raise UnsafeURLError("Enter just the server's name or IP address, like mail.yourbusiness.ca")
    if not (1 <= int(port) <= 65535):
        raise UnsafeURLError("The port must be a number from 1 to 65535.")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError("That address points to a private network.")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError("We couldn't find that server. Check the name for typos.")
    for info in infos:
        if not _ip_is_public(info[4][0]):
            raise UnsafeURLError("That address points to a private network.")
    return infos[0][4][0]


def safe_api_request(url: str, method: str = "GET", headers: dict = None, body: str = None,
                     timeout: int = 15, max_bytes: int = 1_000_000):
    """
    Call a customer's API once. Public addresses only; redirects are NOT followed
    (an API answering with a redirect is reported as that status code).
    """
    import time
    check_url_is_safe(url)
    h = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    h.update(headers or {})
    if body and method == "POST":
        h.setdefault("Content-Type", "application/json")
    started = time.monotonic()
    with requests.request(method, url, headers=h, data=body.encode() if (body and method == "POST") else None,
                          timeout=timeout, allow_redirects=False, stream=True) as r:
        chunks, size = [], 0
        if method != "HEAD":
            for chunk in r.iter_content(16384):
                chunks.append(chunk); size += len(chunk)
                if size >= max_bytes:
                    break
        seconds = round(time.monotonic() - started, 3)
        text = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        return {"status": r.status_code, "seconds": seconds, "text": text}
