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
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

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

# ─── Notification (Telegram) ───────────────────────────────────────────────
# GitHub Actions secrets needed:
#   TELEGRAM_TOKEN   — bot token from BotFather
#   TELEGRAM_CHANNEL — channel username e.g. @ZaraILSaleAlerts
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@ZaraILSaleAlerts")

# Expected next sale date (update each season)
NEXT_SALE_DATE = datetime(2026, 6, 21, tzinfo=timezone.utc)

# Reminders to send: (id, days_offset, message)
# Negative offset = before sale, positive = after
SALE_REMINDERS = [
    ("pre_2w", -14, "🗓 <b>Zara IL sale expected in ~2 weeks</b>\n\nEstimated start: Jun 21. Monitor will auto-detect when it goes live.\n\n📊 <a href=\"https://zivlederer.github.io/zara-sale-monitor/\">Monitor</a>"),
    ("pre_1w",  -7, "⏰ <b>Zara IL sale expected in ~1 week!</b>\n\nEst. start: Jun 21. Could be earlier — monitor is checking daily.\n\n📊 <a href=\"https://zivlederer.github.io/zara-sale-monitor/\">Monitor</a>"),
    ("post_1w", +7, "👀 <b>Zara IL sale window is open</b>\n\nPast the estimated start date. No men's sale detected yet — but it could drop any day.\n\n📊 <a href=\"https://zivlederer.github.io/zara-sale-monitor/\">Monitor</a>"),
    ("post_2w", +14, "📅 <b>Still within Zara IL sale window</b>\n\nTwo weeks past estimated date. Monitor is still watching daily.\n\n📊 <a href=\"https://zivlederer.github.io/zara-sale-monitor/\">Monitor</a>"),
]


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


# ─── Notification ──────────────────────────────────────────────────────────

def send_telegram(message: str):
    """Post message to Telegram channel via bot."""
    if not TELEGRAM_TOKEN:
        print("  [notify] No token — skipping Telegram")
        return
    try:
        params = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHANNEL,
            "text": message,
            "parse_mode": "HTML",
        })
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?{params}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            print(f"  [notify] Telegram sent OK (HTTP {resp.status})")
    except Exception as e:
        print(f"  [notify] Telegram failed: {e}")


def fire_reminders(sent_ids: list) -> list:
    """
    Check if today falls on a reminder milestone.
    Send if not already sent. Returns updated sent_ids list.
    """
    now = datetime.now(timezone.utc)
    for rid, offset_days, msg in SALE_REMINDERS:
        if rid in sent_ids:
            continue
        target = NEXT_SALE_DATE + timedelta(days=offset_days)
        # Fire if we've passed the target day (within a 2-day window to catch missed runs)
        days_past = (now - target).days
        if 0 <= days_past <= 2:
            print(f"  [reminder] Firing reminder: {rid}")
            send_telegram(msg)
            sent_ids.append(rid)
    return sent_ids


def load_previous_state() -> tuple:
    """Return (prev_status, sent_reminder_ids) from status.json."""
    path = os.path.join(os.path.dirname(__file__), "status.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return (
            data.get("verdict", {}).get("status"),
            data.get("reminders_sent", []),
        )
    except Exception:
        return None, []


def maybe_notify(prev_status: str, new_status: str, new_result: dict):
    """Send WhatsApp only when sale status changes."""
    if prev_status == new_status:
        return  # no change, stay quiet

    shop_url = new_result.get("sale_url", "https://www.zara.com/il/en/")
    site_url = "https://zivlederer.github.io/zara-sale-monitor/"

    if new_status == "major_sale":
        items = new_result.get("man_count", 0)
        msg = (
            f"🔥 <b>ZARA IL MEN'S SALE IS ON!</b>\n\n"
            f"{items} men's items detected on sale.\n\n"
            f"🛍 <a href=\"{shop_url}\">Shop now</a>\n"
            f"📊 <a href=\"{site_url}\">Monitor</a>"
        )
        send_telegram(msg)
    elif new_status == "special_prices":
        items = new_result.get("man_count", 0)
        msg = (
            f"🏷 <b>Zara IL — Small Men's Sale</b>\n\n"
            f"{items} items found. Not a major sale yet.\n\n"
            f"🛍 <a href=\"{shop_url}\">Check it out</a>"
        )
        send_telegram(msg)
    elif new_status == "no_sale" and prev_status in ("major_sale", "special_prices"):
        send_telegram("✅ <b>Zara IL men's sale has ended.</b>")


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("Zara IL Men's Sale Monitor — starting check...")
    started = datetime.now(timezone.utc).isoformat()
    prev_status, sent_reminder_ids = load_previous_state()
    print(f"  Previous status: {prev_status}, reminders sent: {sent_reminder_ids}")

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

    # Fire date-based reminders (only when no active sale — don't double-notify)
    if verdict["status"] != "major_sale":
        sent_reminder_ids = fire_reminders(sent_reminder_ids)

    result = {
        "checked_at": started,
        "sale_url": SALE_URL,
        "man_count": count,
        "sample_products": products[:SAMPLE_LIMIT],
        "verdict": verdict,
        "threshold": MAJOR_SALE_THRESHOLD,
        "reminders_sent": sent_reminder_ids,
        "error": None,
    }
    save(result)
    print(f"  Verdict: {verdict['label']} — {verdict['message']}")
    maybe_notify(prev_status, verdict["status"], result)


def save(data: dict):
    path = os.path.join(os.path.dirname(__file__), "status.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved -> {path}")


if __name__ == "__main__":
    main()
