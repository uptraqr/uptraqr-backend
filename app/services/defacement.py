"""
Defacement monitoring — spots when a website has been changed by an attacker.

How it works, in plain English:
1. "Learn" the page: fetch it twice. Anything that differs between the two
   fetches (dates, rotating banners, security codes) is normal movement, so
   we ignore it from then on. What's left is the "known good" baseline.
2. Every 30 minutes, fetch the page again and compare against the baseline.
3. Look for real attack signs, not just "something changed":
   - hacker bragging text ("hacked by ...")
   - scripts, iframes or forms that now load/send to unknown websites
     (card skimmers, crypto miners, fake login forms)
   - the page sending visitors to another website
   - hidden spam links (casino, pharmacy, ...)
   - the title, main heading or most of the text being replaced
4. Each finding gets a severity. Only "high" and "medium" send an alert,
   and the same set of findings never alerts twice.
5. If the owner changed their own site, they press "Approve" and the
   current page becomes the new baseline.
"""
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from app.services.safe_fetch import safe_get, UnsafeURLError

# ---------- What we look for -------------------------------------------------

HACKER_PHRASES = [
    r"hacked\s+by", r"h[a4]ck[e3]d\s+by", r"defaced\s+by", r"owned\s+by\s+\w",
    r"pwn[e3]d\s+by", r"was\s+here", r"greetz", r"greets\s+to", r"security\s+is\s+an\s+illusion",
    r"your\s+site\s+(has\s+been|is)\s+hacked", r"cyber\s+army", r"team\s+\w+\s+was\s+here",
]
SPAM_WORDS = [
    "casino", "viagra", "cialis", "slot gacor", "togel", "judi online", "payday loan",
    "replica watches", "porn", "xxx", "escort", "bitcoin doubler", "online pharmacy",
]
MINER_HINTS = ["coinhive", "cryptoloot", "coin-hive", "webminepool", "minero.cc", "cryptonight", "coinimp"]
SKIMMER_HINTS = {
    "scrambled code that unpacks itself (eval/atob)": r"eval\s*\(\s*atob\s*\(",
    "scrambled code written into the page (document.write/unescape)": r"document\.write\s*\(\s*unescape\s*\(",
    "code hidden as character numbers (fromCharCode)": r"String\.fromCharCode\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+",
}

NUMBERISH = re.compile(r"\d+")
SPACES = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Lowercase, collapse spaces, and blank out numbers (dates, counters, prices)."""
    return SPACES.sub(" ", NUMBERISH.sub("#", text.lower())).strip()


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _site(host: str) -> str:
    """Rough 'registered domain': last two labels (shop.example.com -> example.com)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


# ---------- Reading the page -------------------------------------------------

class _PageReader(HTMLParser):
    SKIP_TEXT = {"script", "style", "noscript", "template", "svg"}

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.title, self.h1 = "", []
        self.blocks, self.scripts, self.iframes, self.forms, self.links = [], set(), set(), set(), set()
        self.inline_js = []
        self.meta_refresh = ""
        self._stack, self._buf, self._in_title, self._in_h1, self._in_script = [], [], False, False, False

    def _abs(self, u):
        return urljoin(self.base, u.strip()) if u else ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._stack.append(tag)
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self.h1.append("")
        elif tag == "script":
            self._in_script = True
            if a.get("src"):
                self.scripts.add(self._abs(a["src"]))
        elif tag == "iframe" and a.get("src"):
            self.iframes.add(self._abs(a["src"]))
        elif tag == "form":
            self.forms.add(self._abs(a.get("action") or self.base))
        elif tag == "a" and a.get("href"):
            href = self._abs(a["href"])
            if href.startswith("http"):
                self.links.add(href)
        elif tag == "meta" and (a.get("http-equiv") or "").lower() == "refresh":
            self.meta_refresh = a.get("content") or ""
        if tag in ("p", "div", "li", "td", "h1", "h2", "h3", "h4", "section", "article", "br", "a", "span"):
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script":
            self._in_script = False
        if tag in ("p", "div", "li", "td", "h1", "h2", "h3", "h4", "section", "article", "a", "span"):
            self._flush()
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_script:
            self.inline_js.append(data)
            return
        if self._stack and self._stack[-1] in self.SKIP_TEXT:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_h1 and self.h1:
            self.h1[-1] += data
        self._buf.append(data)

    def _flush(self):
        text = SPACES.sub(" ", "".join(self._buf)).strip()
        self._buf = []
        if len(text) >= 3:
            self.blocks.append(text)


def read_page(url: str, html: str) -> dict:
    p = _PageReader(url)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    p._flush()
    js = "\n".join(p.inline_js)[:300_000]
    return {
        "title": SPACES.sub(" ", p.title).strip(),
        "h1": [SPACES.sub(" ", h).strip() for h in p.h1 if h.strip()][:5],
        "blocks": p.blocks[:2000],
        "scripts": sorted(p.scripts)[:300],
        "iframes": sorted(p.iframes)[:100],
        "forms": sorted(p.forms)[:100],
        "link_domains": sorted({_domain(l) for l in p.links if _domain(l)})[:500],
        "meta_refresh": p.meta_refresh[:300],
        "inline_js_flags": sorted({label for label, pat in SKIMMER_HINTS.items() if re.search(pat, js)}
                                  | {f"crypto-miner code ({m})" for m in MINER_HINTS if m in js.lower()}),
    }


# ---------- Learning a baseline ----------------------------------------------

def build_baseline(url: str) -> dict:
    """Fetch twice; blocks that change between fetches are 'volatile' and ignored later."""
    final1, status1, html1 = safe_get(url)
    final2, status2, html2 = safe_get(url)
    a, b = read_page(final1, html1), read_page(final2, html2)
    stable = [blk for blk in a["blocks"] if blk in set(b["blocks"])]
    volatile = sorted({_norm(x) for x in set(a["blocks"]) ^ set(b["blocks"])})[:500]
    return {
        "final_url": final2,
        "title": b["title"],
        "h1": b["h1"],
        "blocks": stable,
        "volatile": volatile,
        "scripts": sorted(set(a["scripts"]) | set(b["scripts"])),
        "iframes": sorted(set(a["iframes"]) | set(b["iframes"])),
        "forms": sorted(set(a["forms"]) | set(b["forms"])),
        "link_domains": sorted(set(a["link_domains"]) | set(b["link_domains"])),
        "meta_refresh": b["meta_refresh"],
        "inline_js_flags": sorted(set(a["inline_js_flags"]) | set(b["inline_js_flags"])),
        "learned_at": datetime.utcnow().isoformat(),
    }


# ---------- Comparing --------------------------------------------------------

def _visible_text(page_blocks, volatile):
    vol = set(volatile)
    return " ".join(_norm(b) for b in page_blocks if _norm(b) not in vol)


def _similarity(a: str, b: str) -> float:
    """How much of the page's wording is still the same (0..1), using 3-word phrases."""
    def shingles(t):
        w = t.split()
        return {" ".join(w[i:i + 3]) for i in range(max(len(w) - 2, 1))}
    sa, sb = shingles(a), shingles(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _new_external(urls_now, urls_before, home_site):
    """Entries whose domain is new AND not part of the customer's own site."""
    before_domains = {_domain(u) for u in urls_before}
    out = []
    for u in urls_now:
        d = _domain(u)
        if d and d not in before_domains and _site(d) != home_site:
            out.append(u)
    return out


def compare(baseline: dict, current: dict, current_url: str) -> list:
    """Return a list of findings: {severity, code, message, evidence}."""
    findings = []
    home_site = _site(_domain(baseline.get("final_url") or current_url))

    def add(sev, code, msg, evidence=""):
        findings.append({"severity": sev, "code": code, "message": msg, "evidence": str(evidence)[:200]})

    # Redirected to another website?
    if _site(_domain(current_url)) != home_site:
        add("high", "redirect", "Your page now sends visitors to a different website.", _domain(current_url))
    if current["meta_refresh"] and current["meta_refresh"] != baseline.get("meta_refresh"):
        target = current["meta_refresh"].split("url=")[-1] if "url=" in current["meta_refresh"].lower() else ""
        if target and _site(_domain(urljoin(current_url, target.strip(" '\"")))) != home_site:
            add("high", "redirect", "A hidden instruction now redirects visitors to another website.", target)

    before_text = _visible_text(baseline.get("blocks", []), baseline.get("volatile", [])) + " " + _norm(baseline.get("title", ""))
    now_text = _visible_text(current["blocks"], baseline.get("volatile", [])) + " " + _norm(current["title"])

    if any(f["code"] == "redirect" for f in findings) and _site(_domain(current_url)) != home_site:
        return findings

    # Hacker bragging text
    for pat in HACKER_PHRASES:
        m = re.search(pat, now_text)
        if m and not re.search(pat, before_text):
            add("high", "hacker_text", "Text typical of a hacked website appeared on your page.", m.group(0))
            break

    # Scripts / iframes / forms to new outside websites
    new_scripts = _new_external(current["scripts"], baseline.get("scripts", []), home_site)
    if new_scripts:
        add("high", "new_script", "Your page now loads code from a website it didn't use before. "
            "Attackers use this to steal card details or mine crypto.", ", ".join(_domain(s) for s in new_scripts[:3]))
    new_iframes = _new_external(current["iframes"], baseline.get("iframes", []), home_site)
    if new_iframes:
        add("high", "new_iframe", "Your page now embeds content from a new outside website.",
            ", ".join(_domain(s) for s in new_iframes[:3]))
    new_forms = _new_external(current["forms"], baseline.get("forms", []), home_site)
    if new_forms:
        add("high", "new_form", "A form on your page now sends what people type to an outside website "
            "(a common way to steal logins or payments).", ", ".join(_domain(s) for s in new_forms[:3]))

    new_flags = set(current["inline_js_flags"]) - set(baseline.get("inline_js_flags", []))
    if new_flags:
        add("high", "suspicious_code", "Hidden scrambled code appeared on your page, a common sign of malware.",
            ", ".join(sorted(new_flags))[:120])

    # Spam
    spam_now = [w for w in SPAM_WORDS if w in now_text and w not in before_text]
    new_link_domains = set(current["link_domains"]) - set(baseline.get("link_domains", []))
    spammy_links = [d for d in new_link_domains if any(w.replace(" ", "") in d for w in SPAM_WORDS)]
    if spam_now or spammy_links:
        add("high", "spam", "Spam words or links (casino, pharmacy, adult) appeared on your page.",
            ", ".join((spam_now + spammy_links)[:4]))

    # Title / heading / overall text
    if _norm(current["title"]) != _norm(baseline.get("title", "")) and baseline.get("title"):
        add("medium", "title_changed", "Your page title changed.",
            f'"{baseline.get("title","")[:60]}" → "{current["title"][:60]}"')
    if baseline.get("h1") and current["h1"] and _norm(current["h1"][0]) != _norm(baseline["h1"][0]):
        add("medium", "heading_changed", "Your main heading changed.",
            f'"{baseline["h1"][0][:60]}" → "{current["h1"][0][:60]}"')

    if before_text.strip():
        similarity = _similarity(before_text, now_text)
        if similarity < 0.5:
            add("medium", "text_replaced", "Most of the text on your page was replaced.", f"{round(similarity*100)}% still the same")
        elif similarity < 0.92:
            add("low", "text_changed", "Some text on your page changed.", f"{round(similarity*100)}% still the same")

    return findings


def overall_status(findings: list) -> str:
    sev = {f["severity"] for f in findings}
    if "high" in sev:
        return "suspicious"
    if "medium" in sev:
        return "changed"
    return "ok"


def findings_key(findings: list) -> str:
    """Fingerprint of what's alertable, so the same problem only alerts once."""
    alertable = sorted((f["code"], f["evidence"]) for f in findings if f["severity"] in ("high", "medium"))
    return hashlib.sha256(json.dumps(alertable).encode()).hexdigest() if alertable else ""


def scan(url: str, baseline: dict) -> dict:
    final, status, html = safe_get(url)
    if status >= 400:
        return {"error": f"Page answered with error {status}", "findings": []}
    current = read_page(final, html)
    findings = compare(baseline, current, final)
    return {"error": None, "findings": findings}


__all__ = ["build_baseline", "scan", "overall_status", "findings_key", "UnsafeURLError"]
