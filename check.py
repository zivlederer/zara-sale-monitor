"""
Zara Israel Men's Sale Monitor — POC
Bypasses Akamai bot protection via curl-cffi Chrome TLS impersonation.
Counts products on Zara IL men's sale page.
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

HOMEPAGE       = "https://www.zara.com/il/en/"
MAN_SALE_URL   = "https://www.zara.com/il/en/man-sale-l1217.html"
WOMAN_SALE_URL = "https://www.zara.com/il/en/woman-sale-l1217.html"  # same page, for sanity
MAJOR_SALE_THRESHOLD = 30  # >30 unique products = major sale
SESSION_WARM_PAUSE_SEC = 2


# ─── Akamai bypass ─────────────────────────────────────────────────────────

def make_session():
    """Start session impersonating Chrome 124 TLS fingerprint + solve Akamai challenge."""
    s = cffi_requests.Session(impersonate="chrome124")
    s.headers.update({
        "Accept-Language": "en-IL,en;q=0.9,he;q=0.8",
    })

    # First hit — gets interstitial challenge page
    r = s.get(HOMEPAGE, timeout=25)
    if len(r.text) > 100_000:
        # No challenge — we're through already
        return s

    # Parse challenge parameters
    pm = re.search(
        r'var i = (\d+);.*var j = i \+ Number\("(\d+)" \+ "(\d+)"\);',
        r.text, re.DOTALL,
    )
    bm = re.search(r'"bm-verify": "([^"]+)"', r.text)
    if not (pm and bm):
        raise RuntimeError("Could not parse Akamai challenge — format may have changed")

    j_val = int(pm.group(1)) + int(pm.group(2) + pm.group(3))

    # Submit proof-of-work solution
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


# ─── Scrape sale page ──────────────────────────────────────────────────────

def count_products(html: str) -> int:
    """Count unique product IDs on a sale page."""
    ids = re.findall(r'data-productid="(\d+)"', html)
    return len(set(ids))


def fetch_sale_page(s, url: str) -> dict:
    """Fetch a sale URL and return count + raw size."""
    r = s.get(url, timeout=25)
    if r.status_code != 200:
        return {"ok": False, "count": 0, "size": len(r.text), "error": f"HTTP {r.status_code}"}
    count = count_products(r.text)
    # Fallback-page sizes (homepage redirect) — ignore these
    is_fallback = len(r.text) in (676_270, 1_133_583, 1_130_283)
    if is_fallback or count == 0:
        return {"ok": True, "count": 0, "size": len(r.text), "error": None}
    return {"ok": True, "count": count, "size": len(r.text), "error": None}


# ─── Decision logic ────────────────────────────────────────────────────────

def classify(count: int) -> dict:
    if count == 0:
        return {"status": "no_sale", "label": "No Sale",
                "message": "No sale products detected"}
    if count < MAJOR_SALE_THRESHOLD:
        return {"status": "special_prices", "label": "Special Prices",
                "message": f"{count} items — small selection (regular Special Prices, not a major sale)"}
    return {"status": "major_sale", "label": "🔥 MAJOR SALE",
            "message": f"{count} items on sale — major seasonal sale active!"}


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("Zara IL Men's Sale Monitor — starting check...")
    started = datetime.now(timezone.utc).isoformat()

    try:
        s = make_session()
        print("  Akamai challenge solved ✓")
    except Exception as e:
        result = {
            "checked_at": started,
            "url": MAN_SALE_URL,
            "count": None,
            "verdict": {"status": "unknown", "label": "Unknown", "message": f"Session init failed: {e}"},
            "threshold": MAJOR_SALE_THRESHOLD,
            "error": str(e),
        }
        save(result)
        print(f"  ERROR: {e}")
        sys.exit(1)

    time.sleep(1)
    info = fetch_sale_page(s, MAN_SALE_URL)
    print(f"  Fetched {MAN_SALE_URL}: count={info['count']} size={info['size']}")

    verdict = classify(info["count"]) if info["ok"] else \
              {"status": "unknown", "label": "Unknown", "message": info["error"]}

    result = {
        "checked_at": started,
        "url": MAN_SALE_URL,
        "count": info["count"] if info["ok"] else None,
        "verdict": verdict,
        "threshold": MAJOR_SALE_THRESHOLD,
        "error": info["error"] if not info["ok"] else None,
    }
    save(result)
    print(f"  Verdict: {verdict['label']} ({verdict['message']})")


def save(data: dict):
    path = os.path.join(os.path.dirname(__file__), "status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved → {path}")


if __name__ == "__main__":
    main()
