"""
Website health report: a one-time check anyone can run without an account.

It loads the homepage once (plus robots.txt, sitemap.xml and the http:// version),
looks up two DNS records, and grades five areas in plain English:
  Security, Hacker signs, Email security, Google & search (SEO), Speed & availability.
Every failed item comes with a short fix a business owner can forward to their web person.
"""
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

import requests

from app.services.safe_fetch import safe_get_detailed, check_url_is_safe, UnsafeURLError
from app.services.ssl_checker import check_ssl
from app.services.defacement import read_page, HACKER_PHRASES, SPAM_WORDS, MINER_HINTS, _norm, _site, _domain

CATEGORY_WEIGHTS = {"security": 30, "hacker": 20, "seo": 20, "speed": 15, "email": 15}
CATEGORY_NAMES = {
    "security": "Security settings",
    "hacker": "Signs of hacking",
    "seo": "Google and search",
    "speed": "Speed and availability",
    "email": "Email protection",
}

# --------------------------------------------------------------------------- helpers

def normalise_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise UnsafeURLError("Enter your website address, for example yourbusiness.ca")
    if len(raw) > 300:
        raise UnsafeURLError("That address is too long.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname or "." not in parsed.hostname:
        raise UnsafeURLError("That doesn't look like a website address. Try something like yourbusiness.ca")
    # Always report on the homepage
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{':' + str(parsed.port) if parsed.port else ''}/"


def _item(ok, label, detail, fix=None, weight=1, level="high"):
    """ok: True (pass), False (fail), None (couldn't tell / informational)."""
    return {"ok": ok, "label": label, "detail": detail, "fix": fix if ok is False else None,
            "weight": weight, "level": level}


def _score(items):
    graded = [i for i in items if i["ok"] is not None]
    total = sum(i["weight"] for i in graded)
    if not total:
        return None
    return round(sum(i["weight"] for i in graded if i["ok"]) / total * 100)


def grade(score):
    if score is None:
        return "?"
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"


class _SeoReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.meta = {}
        self.links = {}
        self.h1 = 0
        self.imgs = 0
        self.imgs_no_alt = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang") or None
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            for rel in (a.get("rel") or "").lower().split():
                self.links.setdefault(rel, a.get("href", ""))
        elif tag == "h1":
            self.h1 += 1
        elif tag == "img":
            self.imgs += 1
            if not a.get("alt", "").strip():
                self.imgs_no_alt += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _small_get(url):
    """Quick fetch of a small file (robots.txt, sitemap.xml) with the same safety rules."""
    try:
        r = safe_get_detailed(url, max_bytes=200_000)
        return r
    except (requests.RequestException, UnsafeURLError):
        return None


def _txt_records(name):
    try:
        import dns.resolver
        answers = dns.resolver.resolve(name, "TXT", lifetime=4)
        return [b"".join(r.strings).decode(errors="replace") for r in answers]
    except Exception as e:
        if e.__class__.__name__ in ("NXDOMAIN", "NoAnswer"):
            return []
        return None   # lookup failed: unknown


# --------------------------------------------------------------------------- checks

def _speed(page, http_redirects):
    items = []
    secs = page["seconds"]
    items.append(_item(page["status"] < 400, "Your homepage loads",
                       f"It answered with code {page['status']}." if page["status"] >= 400 else "It loaded normally.",
                       "Your homepage is returning an error. Ask your web host or designer to check the site.", weight=3))
    if secs <= 1.5:
        items.append(_item(True, "Loads quickly", f"It took {secs} seconds."))
    elif secs <= 3.5:
        items.append(_item(False, "Loads quickly", f"It took {secs} seconds. Under 1.5 seconds is ideal.",
                           "Ask your web person about image compression, caching or a faster hosting plan.", level="medium"))
    else:
        items.append(_item(False, "Loads quickly", f"It took {secs} seconds. Many visitors leave after 3 seconds.",
                           "Your site is slow. Ask your web person to compress images, turn on caching, or move to faster hosting.", weight=2))
    mb = page["bytes"] / 1_000_000
    items.append(_item(mb < 1.5, "Homepage size is reasonable", f"The page itself is {mb:.1f} MB (not counting images loaded separately).",
                       "The homepage code is very large. Ask your web person to trim unused plugins and scripts.", level="low"))
    if http_redirects is not None:
        items.append(_item(http_redirects, "Visitors are always sent to the secure version",
                           "http:// takes visitors to https://." if http_redirects else "Typing http:// keeps visitors on the insecure version of your site.",
                           "Turn on 'Always use HTTPS' (or a 301 redirect from http to https) at your host or Cloudflare."))
    return items


def _security(page, host, ssl):
    h = page["headers"]
    items = []
    if ssl.get("valid"):
        days = ssl["days_left"]
        items.append(_item(days > 14, "Security certificate (padlock) is valid",
                           f"It's valid for {days} more days." if days > 14 else f"It expires in {days} days.",
                           "Renew your SSL certificate now, or check why automatic renewal isn't working.", weight=3))
    else:
        items.append(_item(False, "Security certificate (padlock) is valid",
                           "We couldn't find a working certificate. Browsers will show 'Not secure'.",
                           "Set up a free SSL certificate (most hosts and Cloudflare offer one with one click).", weight=4))
    headers = [
        ("strict-transport-security", "Forces secure connections (HSTS)",
         "Tells browsers to always use the secure version of your site.",
         "Add the Strict-Transport-Security header (in Cloudflare: SSL/TLS, Edge Certificates, enable HSTS).", 2),
        ("content-security-policy", "Blocks injected scripts (Content Security Policy)",
         "Limits which code can run on your pages, which stops many hacks from working.",
         "Add a Content-Security-Policy header. Your web person can start with a report-only version to test it safely.", 2),
        ("x-frame-options", "Blocks clickjacking",
         "Stops other sites loading yours in a hidden frame to trick people into clicking.",
         "Add the header X-Frame-Options: SAMEORIGIN.", 1),
        ("x-content-type-options", "Blocks file-type tricks",
         "Stops browsers guessing file types, which attackers can abuse.",
         "Add the header X-Content-Type-Options: nosniff.", 1),
        ("referrer-policy", "Limits data shared with other sites",
         "Controls how much of your page addresses are passed to sites you link to.",
         "Add the header Referrer-Policy: strict-origin-when-cross-origin.", 1),
        ("permissions-policy", "Limits camera, microphone and location access",
         "Stops embedded content from asking visitors for these.",
         "Add a Permissions-Policy header, for example camera=(), microphone=(), geolocation=().", 1),
    ]
    csp = h.get("content-security-policy", "")
    for name, label, explain, fix, w in headers:
        present = name in h or (name == "x-frame-options" and "frame-ancestors" in csp)
        items.append(_item(present, label, explain if present else explain + " Not set.", fix, weight=w, level="medium" if w == 1 else "high"))
    server = h.get("x-powered-by") or ""
    if server:
        items.append(_item(False, "Hides software versions", f"Your site announces '{server[:60]}'. This helps attackers pick their tools.",
                           "Ask your web person to remove the X-Powered-By header.", level="low"))
    return items


def _hacker(page):
    parsed = read_page(page["final_url"], page["text"])
    text = " ".join(_norm(b) for b in parsed["blocks"]) + " " + _norm(parsed["title"])
    home = _site(_domain(page["final_url"]))
    items = []
    hit = next((m.group(0) for p in HACKER_PHRASES if (m := re.search(p, text))), None)
    items.append(_item(not hit, "No hacker messages", "None found." if not hit else f"We found '{hit}' on your page.",
                       "Your site may be hacked. Contact your web designer or host right away, change all website passwords, and restore a clean backup.", weight=4))
    spam = [w for w in SPAM_WORDS if w in text] + [d for d in parsed["link_domains"] if any(w.replace(" ", "") in d for w in SPAM_WORDS)]
    items.append(_item(not spam, "No spam links", "None found." if not spam else f"Found: {', '.join(spam[:4])}.",
                       "Hidden spam is a common sign of a hacked site. Ask your web person to scan the site for malware.", weight=3))
    items.append(_item(not parsed["inline_js_flags"], "No disguised code",
                       "None found." if not parsed["inline_js_flags"] else "Found " + ", ".join(parsed["inline_js_flags"]) + ".",
                       "Scrambled code is often malware. Ask your web person to check where it came from.", weight=3))
    leaving = _site(_domain(page["final_url"])) != _site(_domain(page["hops"][0]))
    items.append(_item(not leaving, "Visitors stay on your website",
                       "Your homepage doesn't send visitors elsewhere." if not leaving else f"Your homepage sends visitors to {_domain(page['final_url'])}.",
                       "If you didn't set up this redirect, your site may be hacked. Contact your web person now.", weight=3))
    outside = sorted({_domain(s) for s in parsed["scripts"] if _domain(s) and _site(_domain(s)) != home})
    items.append(_item(None, "Code loaded from other websites",
                       f"{len(outside)} outside source{'s' if len(outside) != 1 else ''}" + (f": {', '.join(outside[:6])}{'…' if len(outside) > 6 else ''}." if outside else ".")
                       + " This is normal for analytics, chat or payment tools, but each one is a possible way in. Tamper watch alerts you if a new one appears."))
    return items, parsed


def _seo(page, robots, sitemap):
    r = _SeoReader()
    try:
        r.feed(page["text"])
    except Exception:
        pass
    title = re.sub(r"\s+", " ", r.title).strip()
    desc = (r.meta.get("description") or "").strip()
    robots_meta = (r.meta.get("robots") or "").lower()
    items = []
    items.append(_item(bool(title) and 10 <= len(title) <= 65, "Page title",
                       f"\"{title[:70]}\" ({len(title)} characters)." if title else "Missing.",
                       "Give your homepage a clear title of 10 to 65 characters with your business name and what you do."
                       if title else "Add a page title with your business name and what you do.", weight=2))
    items.append(_item(bool(desc) and 50 <= len(desc) <= 165, "Search result description",
                       f"{len(desc)} characters." if desc else "Missing. Google will pick random text from your page.",
                       "Write a 50 to 160 character description of your business (the meta description). It's the text people see under your link on Google.", weight=2))
    items.append(_item(r.h1 == 1, "One main heading",
                       {0: "No main heading (H1) found.", 1: "Found one, as recommended."}.get(r.h1, f"Found {r.h1}; one is best."),
                       "Use exactly one main heading (H1) that says what your business does.", level="medium"))
    items.append(_item("viewport" in r.meta, "Works on phones", "Set up for mobile screens." if "viewport" in r.meta else "Not set up for mobile screens.",
                       "Add a mobile viewport tag. Google ranks sites that don't work on phones lower.", weight=2))
    items.append(_item("noindex" not in robots_meta, "Allowed in Google",
                       "Google is allowed to list this page." if "noindex" not in robots_meta else "This page tells Google NOT to list it.",
                       "Remove the 'noindex' setting (often a WordPress 'discourage search engines' tick box).", weight=4))
    items.append(_item(bool(r.links.get("canonical")), "Official address set (canonical)",
                       "Set." if r.links.get("canonical") else "Not set, so Google may treat www and non-www as duplicates.",
                       "Add a canonical link tag pointing to your preferred address.", level="medium"))
    items.append(_item(bool(r.meta.get("og:title") or r.meta.get("og:image")), "Preview when shared",
                       "Links to your site show a title and image on social media." if (r.meta.get("og:title") or r.meta.get("og:image")) else "Links shared on Facebook, LinkedIn or WhatsApp show no preview.",
                       "Add Open Graph tags (og:title, og:description, og:image).", level="low"))
    items.append(_item(bool(r.lang), "Language set", f"Set to '{r.lang}'." if r.lang else "Not set.",
                       "Add a lang attribute to the page, for example lang=\"en\".", level="low"))
    if r.imgs:
        items.append(_item(r.imgs_no_alt == 0, "Images have descriptions",
                           f"{r.imgs_no_alt} of {r.imgs} images have no description (alt text)." if r.imgs_no_alt else f"All {r.imgs} images have descriptions.",
                           "Add short alt text to images. It helps Google and people using screen readers.", level="low"))
    items.append(_item(robots is not None and robots["status"] < 400, "Has a robots.txt file",
                       "Found." if robots is not None and robots["status"] < 400 else "Not found.",
                       "Add a robots.txt file so search engines know what to crawl.", level="low"))
    head = sitemap["text"][:5000] if sitemap is not None and sitemap["status"] < 400 else ""
    has_map = "<urlset" in head or "<sitemapindex" in head
    items.append(_item(bool(has_map), "Has a sitemap", "Found." if has_map else "Not found at /sitemap.xml.",
                       "Add a sitemap and submit it in Google Search Console so Google finds all your pages.", level="medium"))
    return items


def _email(host):
    apex = _site(host)
    items = []
    spf = _txt_records(apex)
    if spf is None:
        items.append(_item(None, "Sender protection (SPF)", "We couldn't look this up right now."))
    else:
        rec = next((t for t in spf if t.lower().startswith("v=spf1")), None)
        items.append(_item(bool(rec), "Sender protection (SPF)",
                           "Set up. It lists which services may send email as your domain." if rec else "Missing. Anyone can send email pretending to be from your domain.",
                           "Add an SPF record in your DNS listing the services that send your email (your email provider can give you this).", weight=2))
    dmarc = _txt_records("_dmarc." + apex)
    if dmarc is None:
        items.append(_item(None, "Fake email protection (DMARC)", "We couldn't look this up right now."))
    else:
        rec = next((t for t in dmarc if t.lower().startswith("v=dmarc1")), None)
        if not rec:
            items.append(_item(False, "Fake email protection (DMARC)", "Missing. Scammers can send convincing fake emails from your domain.",
                               "Add a DMARC record. Start with v=DMARC1; p=none; then tighten to p=quarantine once your real emails pass.", weight=2))
        else:
            policy = (re.search(r"\bp=(\w+)", rec.lower()) or [None, "none"])[1]
            items.append(_item(policy in ("quarantine", "reject"), "Fake email protection (DMARC)",
                               f"Set to '{policy}'." + ("" if policy in ("quarantine", "reject") else " Fake emails are reported but still delivered."),
                               "Change your DMARC policy from p=none to p=quarantine once your real emails pass checks.", level="medium"))
    return items


# --------------------------------------------------------------------------- main

def run_report(raw_url: str) -> dict:
    url = normalise_url(raw_url)
    check_url_is_safe(url)
    started = time.monotonic()
    try:
        page = safe_get_detailed(url)
    except requests.exceptions.SSLError:
        # try plain http so we can still report something useful
        url = url.replace("https://", "http://", 1)
        page = safe_get_detailed(url)
    host = urlparse(page["final_url"]).hostname or urlparse(url).hostname
    origin = f"{urlparse(page['final_url']).scheme}://{host}"

    http_redirects = None
    if url.startswith("https://"):
        try:
            hp = safe_get_detailed("http://" + url[len("https://"):], max_bytes=20_000)
            http_redirects = hp["final_url"].startswith("https://")
        except (requests.RequestException, UnsafeURLError):
            http_redirects = None
    ssl = check_ssl(host) if page["final_url"].startswith("https://") else {"valid": False}
    robots = _small_get(origin + "/robots.txt")
    sitemap = _small_get(origin + "/sitemap.xml")

    hacker_items, _ = _hacker(page)
    categories = {
        "security": _security(page, host, ssl),
        "hacker": hacker_items,
        "seo": _seo(page, robots, sitemap),
        "speed": _speed(page, http_redirects),
        "email": _email(host),
    }
    cats = []
    weighted, weight_total = 0, 0
    for key in ["hacker", "security", "speed", "seo", "email"]:
        sc = _score(categories[key])
        cats.append({"key": key, "name": CATEGORY_NAMES[key], "score": sc, "grade": grade(sc), "items": categories[key]})
        if sc is not None:
            weighted += sc * CATEGORY_WEIGHTS[key]
            weight_total += CATEGORY_WEIGHTS[key]
    overall = round(weighted / weight_total) if weight_total else None
    rank = {"high": 0, "medium": 1, "low": 2}
    fixes = sorted(
        [dict(i, category=c["name"]) for c in cats for i in c["items"] if i["ok"] is False],
        key=lambda i: (rank[i["level"]], -i["weight"]),
    )
    return {
        "url": url,
        "final_url": page["final_url"],
        "host": host,
        "score": overall,
        "grade": grade(overall),
        "categories": cats,
        "fixes": fixes,
        "hacked": any(i["ok"] is False for i in categories["hacker"]),
        "seconds": round(time.monotonic() - started, 1),
    }
