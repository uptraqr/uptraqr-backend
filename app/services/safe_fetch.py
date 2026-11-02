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


def safe_get(url: str):
    """
    Fetch a page, checking every hop. Returns (final_url, status_code, html_text).
    Raises UnsafeURLError or requests.RequestException.
    """
    current = url
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    for _ in range(MAX_REDIRECTS + 1):
        check_url_is_safe(current)
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
            if total >= MAX_BYTES:
                break
        resp.close()
        encoding = resp.encoding or "utf-8"
        text = b"".join(chunks).decode(encoding, errors="replace")
        return current, resp.status_code, text
    raise requests.TooManyRedirects("Too many redirects")
