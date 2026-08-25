"""Fetch the headline article's official og:image as the digest cover.

News/product sites put their share image in <meta property="og:image"> — that
is the "official picture" the user wants for social publishing. Never fails
the pipeline: returns the saved file name or an empty string.
"""

import re
from datetime import datetime

import requests

from config import BEIJING_TZ, OUTPUT_DIR

_OG_PATTERNS = [
    r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
    r'<meta[^>]+property=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']twitter:image["\']',
]
_USER_AGENT = "Mozilla/5.0 (compatible; AI-DailyPulse/1.0)"
_MAX_BYTES = 5 * 1024 * 1024


def _find_og_image(page_url: str, timeout: int = 15) -> str:
    resp = requests.get(page_url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    for pat in _OG_PATTERNS:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1)
    return ""


def fetch_cover(article_url: str) -> str:
    """Download the og:image of the article's site to output/, return its file name.

    Returns "" (and logs) when no image can be fetched — a missing cover must
    never break the pipeline.
    """
    try:
        img_url = _find_og_image(article_url)
        if not img_url:
            print("[cover] no og:image found on the headline page")
            return ""

        resp = requests.get(img_url, headers={"User-Agent": _USER_AGENT}, timeout=20)
        resp.raise_for_status()
        if len(resp.content) < 1000:
            print(f"[cover] og:image too small ({len(resp.content)} bytes)")
            return ""
        if len(resp.content) > _MAX_BYTES:
            print(f"[cover] og:image too large ({len(resp.content)} bytes)")
            return ""

        ctype = resp.headers.get("Content-Type", "").lower()
        # extensions by content type is safer than by url tail
        ext = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg"}.get(ctype.split(";")[0], ".jpg")

        fname = f"cover_{datetime.now(BEIJING_TZ).strftime('%Y%m%d')}{ext}"
        (OUTPUT_DIR / fname).write_bytes(resp.content)
        print(f"[cover] saved {fname} ({len(resp.content)} bytes)")
        return fname
    except Exception as e:
        print(f"[cover] fetch failed: {e}")
        return ""


if __name__ == "__main__":
    import sys
    print("cover:", repr(fetch_cover(sys.argv[1])))
