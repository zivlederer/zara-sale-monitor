"""
Zara Israel Men's Sale Monitor — POC
Bypasses Akamai bot protection via curl-cffi Chrome TLS impersonation.
Fetches the Zara IL sale page and counts MEN-section products specifically.
"""

import sys
import json
import re
import time
import os
from datetime import datetime, timezone

# Force UTF-8 stdout (Windows fix)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from curl_cffi import requests as cffi_requests

# ─── Config ────────────────────────────────────────────────────────────────

HOMEPAGE = "https://www.zara.com/il/en/"

# The active sale page on Zara IL. Contains mixed-gender products;
# we filter to sectionName=MAN explicitly.
# l1217 = current IL sale category (confirmed active April 2026)
SALE_URL = "https://www.zara.com/il/en/woman-sale-l1217.html"

MAJOR_SALE_THRESHOLD = 10  # >10 unique MAN products = major sale
SAMPLE_LIMIT = 6
SESSION_WARM_PAUSE_SEC = 2


# ─── Akamai bypass ─────────────────────────────────────────────────────────

def make_session():
    s = cffi_requests.Session(impersonate="chrome124")
    s.headers.update({"Accept-Language": "en-IL,en;q=0.9,he;q=0.8"})

    r = s.get(HOMEPAGE, timeout=25)
    if "bm-verify" not in r.text:
        return s  # no challenge, already through

    pm = re.search(
        r'var i = (\d+);.*var j = i \+ Number\("(\d+)" \+ "(\d+)"\);',
        r.text, re.DOTALL,
    )
    bm = re.search(r'"bm-verify": "([^"]+)"', r.text)
    if not (pm and bm):
        raise RuntimeError("Akamai challenge format changed — update parser")

    j_val = int(pm.group(1)) + int(pm.group(2) + pm.group(3))
    verify = s.post(
        "https://www.zara.com/_sec/verify?provider=interstitial",
        data=json.dumps({"bm-verify": bm.group(1), "pow": j_val}),
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    if verify.status_code != 200:
        raise RuntimeError(f"Akamai verify POST failed: HTTP {verify.status_code}")

    time.sleep(SESSION_WARM_PAUSE_SEC)
    return s


# ─── Product extraction (MAN section only) ─────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_man_products(html: str) -> list:
    """
    Parse the embedded script JSON blob for MAN-section products.
    Product JSON: "name":"X",...,"section":2,"sectionName":"MAN",...,"reference":"XXXXXXXX-"
    URL format:   /il/en/{slug}-p{8-digit-ref}.html
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    big = max(scripts, key=len) if scripts else ""

    # Find products where sectionName=MAN, then get their name + reference
    # Structure: "name":"X" ... "sectionName":"MAN" ... "reference":"XXXXXXXX-V20XX"
    pairs = re.findall(
        r'"name":"([A-Z][^"]{2,60})".{0,600}?"section":2,"sectionName":"MAN".{0,600}?"reference":"(\d{8})-',
        big,
    )

    seen = {}
    for name, ref in pairs:
        if ref not in seen:
            url = f"https://www.zara.com/il/en/{slugify(name)}-p{ref}.html"
            seen[ref] = {"name": name.title(), "ref": ref, "url": url}

    return list(seen.values())


# ─── Classify count ────────────────────────────────────────────────────────

def classify(count: int) -> dict:
    if count == 0:
        return {
            "status": "no_sale",
            "label": "No Men's Sale",
            "message": "No men's sale products detected on Zara IL right now",
        }
    if count < MAJOR_SALE_THRESHOLD:
        return {
            "status": "special_prices",
            "label": "Special Prices",
            "message": f"{count} men's items — small selection, not a major sale",
        }
    return {
        "status": "major_sale",
        "label": "MAJOR SALE",
        "message": f"{count} men's items on sale — major seasonal sale active!",
    }


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("Zara IL Men's Sale Monitor — starting check...")
    started = datetime.now(timezone.utc).isoformat()

    try:
        s = make_session()
        print("  Akamai challenge solved")
    except Exception as e:
        save({
            "checked_at": started,
            "sale_url": SALE_URL,
            "man_count": None,
            "sample_products": [],
            "verdict": {"status": "unknown", "label": "Unknown", "message": str(e)},
            "threshold": MAJOR_SALE_THRESHOLD,
            "error": str(e),
        })
        sys.exit(1)

    time.sleep(1)
    r = s.get(SALE_URL, timeout=25)
    print(f"  Fetched {SALE_URL}: HTTP {r.status_code} size={len(r.text)}")

    if r.status_code != 200:
        save({
            "checked_at": started,
            "sale_url": SALE_URL,
            "man_count": None,
            "sample_products": [],
            "verdict": {"status": "unknown", "label": "Unknown", "message": f"HTTP {r.status_code}"},
            "threshold": MAJOR_SALE_THRESHOLD,
            "error": f"HTTP {r.status_code}",
        })
        sys.exit(1)

    products = extract_man_products(r.text)
    count = len(products)
    print(f"  Men's products found: {count}")
    verdict = classify(count)

    result = {
        "checked_at": started,
        "sale_url": SALE_URL,
        "man_count": count,
        "sample_products": products[:SAMPLE_LIMIT],
        "verdict": verdict,
        "threshold": MAJOR_SALE_THRESHOLD,
        "error": None,
    }
    save(result)
    print(f"  Verdict: {verdict['label']} — {verdict['message']}")


def save(data: dict):
    path = os.path.join(os.path.dirname(__file__), "status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved -> {path}")


if __name__ == "__main__":
    main()
