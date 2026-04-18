# Zara Israel — Men's Sale Monitor

Free, auto-updating status page that checks if Zara IL men's sale is active.

## How it works

- **GitHub Actions** runs `check.py` daily (07:00 UTC) + on manual dispatch.
- `check.py` bypasses Zara's Akamai bot protection via `curl-cffi` (Chrome TLS fingerprint impersonation + solves the interstitial PoW challenge), then counts products on [`man-sale-l1217.html`](https://www.zara.com/il/en/man-sale-l1217.html).
- Result is written to `status.json`, committed back to the repo.
- **GitHub Pages** serves `index.html`, which fetches `status.json` and renders the verdict.

## Sale classification

| Count | Verdict |
|-------|---------|
| 0 | ✅ No Sale |
| 1–29 | 🏷️ Special Prices (regular, not a major sale) |
| ≥ 30 | 🔥 MAJOR SALE |

## Manual check

Actions tab → **Check Zara Israel Sale** → *Run workflow*.

## Local dev

```bash
pip install -r requirements.txt
python check.py
```
