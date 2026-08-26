import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime

import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL,
    WP_URL,
    WP_USER,
    WP_APP_PASSWORD,
    FEISHU_WEBHOOK_URL,
    FEISHU_SECRET,
    BEIJING_TZ,
    DIGEST_OUTPUT,
    SOCIAL_OUTPUT,
    OUTPUT_DIR,
)


# ─── Telegram ───────────────────────────────────────────

def _telegram_api(text: str, parse_mode: str | None) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "text": text,
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return True
        print(f"[publish] Telegram error: {data.get('description')}")
    except Exception as e:
        print(f"[publish] Telegram failed: {e}")
    return False


def publish_telegram(text: str) -> bool:
    """Send a single message to a Telegram channel, plain-text fallback."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
        print("[publish] Telegram not configured, skip")
        return False
    if _telegram_api(text, "Markdown"):
        return True
    return _telegram_api(text, None)


def publish_telegram_digest(digest: str) -> bool:
    """Send the daily digest as one message per article section."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
        print("[publish] Telegram not configured, skip")
        return False

    sent = 0
    for section in re.split(r"\n(?=### )", digest):
        text = section.strip()
        if not text:
            continue
        for i in range(0, len(text), 4000):
            if publish_telegram(text[i:i + 4000]):
                sent += 1
            time.sleep(1)
    print(f"[publish] Telegram sent {sent} messages")
    return sent > 0


# ─── WordPress ──────────────────────────────────────────

def publish_wordpress(title: str, content: str, status: str = "draft") -> bool:
    """Publish a post to WordPress via REST API."""
    if not WP_URL or not WP_USER or not WP_APP_PASSWORD:
        print("[publish] WordPress not configured, skip")
        return False

    api_url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    try:
        resp = requests.post(
            api_url,
            json={
                "title": title,
                "content": content,
                "status": status,
                "categories": [1],
            },
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=20,
        )
        if resp.status_code == 201:
            print(f"[publish] WordPress draft: {resp.json().get('link')}")
            return True
        else:
            print(f"[publish] WordPress error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[publish] WordPress failed: {e}")
    return False


# ─── Feishu ─────────────────────────────────────────────

def _feishu_sign(timestamp: str, secret: str) -> str:
    # Feishu's scheme: the HMAC key is "{timestamp}\n{secret}" with an empty message
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _markdown_to_feishu_text(md: str) -> str:
    """Convert basic markdown to Feishu-friendly plain text."""
    # remove heading markers, keep text
    md = re.sub(r'^#+\s*', '', md, flags=re.MULTILINE)
    # bold: **text** -> 【text】
    md = re.sub(r'\*\*(.+?)\*\*', r'【\1】', md)
    # italic: *text* -> text
    md = re.sub(r'\*(.+?)\*', r'\1', md)
    # inline code: `text` -> text
    md = re.sub(r'`(.+?)`', r'\1', md)
    # horizontal rules
    md = re.sub(r'^---+\s*$', '―' * 20, md, flags=re.MULTILINE)
    # links: [text](url) -> text (url)
    md = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1 (\2)', md)
    return md


def publish_feishu(digest: str) -> bool:
    """Send the daily digest to Feishu via bot webhook (single message)."""
    if not FEISHU_WEBHOOK_URL:
        print("[publish] Feishu not configured, skip")
        return False

    success_count = 0

    def _send(text: str) -> bool:
        body = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if FEISHU_SECRET:
            ts = str(int(datetime.now().timestamp()))
            body["timestamp"] = ts
            body["sign"] = _feishu_sign(ts, FEISHU_SECRET)
        try:
            resp = requests.post(FEISHU_WEBHOOK_URL, json=body, timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return True
            print(f"[publish] Feishu error: {data.get('code')} {data.get('msg')}")
        except Exception as e:
            print(f"[publish] Feishu request failed: {e}")
        return False

    try:
        # v2 digest is short (headline + 4 picks): send it whole,
        # chunk only if it somehow exceeds the message limit
        text = _markdown_to_feishu_text(digest.strip())
        chunks = [text[i:i+25000] for i in range(0, len(text), 25000)]
        for chunk in chunks:
            if _send(chunk):
                success_count += 1
            time.sleep(0.3)
    except Exception as e:
        print(f"[publish] Feishu failed: {e}")
        return False

    print(f"[publish] Feishu sent {success_count} messages")
    return success_count > 0


# ─── File export for manual review ──────────────────────

def save_manual_posts(posts_map: dict):
    """Save social media posts as individual files for manual review/publishing."""
    if not posts_map:
        return

    manual_dir = OUTPUT_DIR / "manual_review"
    manual_dir.mkdir(exist_ok=True)
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")

    for article_id, platforms in posts_map.items():
        for platform, content in platforms.items():
            if not content:
                continue
            ext = "md"
            fname = f"{today}_{platform}_{article_id[:8]}.{ext}"
            (manual_dir / fname).write_text(content, encoding="utf-8")

    print(f"[publish] saved {len(posts_map)} articles' social posts to {manual_dir}")


def save_daily_files(digest: str):
    """Save the daily digest and social posts as permanent files."""
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")

    # Copy digest to dated file
    dated_digest = OUTPUT_DIR / f"digest_{today}.md"
    dated_digest.write_text(digest, encoding="utf-8")
    print(f"[publish] saved {dated_digest}")

    # Save a short version for WeChat (first 2000 chars of digest body)
    short = "\n".join(digest.split("\n")[:80])
    wechat_file = OUTPUT_DIR / f"wechat_draft_{today}.md"
    wechat_file.write_text(short, encoding="utf-8")
    print(f"[publish] saved wechat draft: {wechat_file}")


# ─── Orchestrator ───────────────────────────────────────

def publish_all(digest: str, posts_map: dict):
    """Run all publishing steps."""
    results = {}
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

    # 1. Feishu - instant push (digest only; social posts live in output files)
    results["feishu"] = publish_feishu(digest)

    # 2. Telegram - instant push
    results["telegram"] = publish_telegram_digest(digest)

    # 3. WordPress - draft (safe, won't auto-publish)
    title = f"AI DailyPulse | {today}"
    wp_preview = digest[:10000].rstrip() + "\n\n[完整版见公众号]"
    results["wordpress"] = publish_wordpress(title, wp_preview, status="draft")

    # 4. Save for manual review (WeChat, XHS, Zhihu)
    save_manual_posts(posts_map)
    save_daily_files(digest)

    return results


if __name__ == "__main__":
    if DIGEST_OUTPUT.exists():
        digest = DIGEST_OUTPUT.read_text(encoding="utf-8")
        posts = {}
        if SOCIAL_OUTPUT.exists():
            posts = json.loads(SOCIAL_OUTPUT.read_text(encoding="utf-8"))
        results = publish_all(digest, posts)
        print(f"[publish] done: {results}")
    else:
        print("[publish] no digest file found")
