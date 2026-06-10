import json
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
    DIGEST_OUTPUT,
    SOCIAL_OUTPUT,
    OUTPUT_DIR,
)


# ─── Telegram ───────────────────────────────────────────

def publish_telegram(text: str) -> bool:
    """Send a message to a Telegram channel."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
        print("[publish] Telegram not configured, skip")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHANNEL,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }, timeout=15)
        data = resp.json()
        if data.get("ok"):
            print("[publish] Telegram sent")
            return True
        else:
            print(f"[publish] Telegram error: {data.get('description')}")
            # retry without markdown parse
            resp2 = requests.post(url, json={
                "chat_id": TELEGRAM_CHANNEL,
                "text": text,
            }, timeout=15)
            if resp2.json().get("ok"):
                print("[publish] Telegram sent (plain text fallback)")
                return True
    except Exception as e:
        print(f"[publish] Telegram failed: {e}")
    return False


def publish_telegram_digest(digest: str):
    """Send the daily digest as a series of Telegram messages."""
    # send a short summary first
    lines = digest.split("\n")
    today = datetime.now().strftime("%Y-%m-%d")

    # first message: headline + top items
    intro = f"🤖 *AI/科技早报 | {today}*\n\n"
    quick_section = False
    quick_items = []
    for line in lines:
        if "今日速览" in line:
            quick_section = True
            continue
        if quick_section and line.startswith("🔹"):
            quick_items.append(line)
        elif quick_section and line.startswith("---"):
            break

    if quick_items:
        intro += "\n".join(quick_items[:5])

    publish_telegram(intro)

    # send each article as a separate message
    article_count = 0
    for line in lines:
        if line.startswith("## ") and article_count < 8:
            article_count += 1


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

def _markdown_to_feishu_text(md: str) -> str:
    """Convert basic markdown to Feishu-friendly plain text."""
    import re
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


def publish_feishu(digest: str, posts_map: dict = None) -> bool:
    """Send daily digest and social media posts to Feishu via bot webhook."""
    if not FEISHU_WEBHOOK_URL:
        print("[publish] Feishu not configured, skip")
        return False

    # split digest into the overview section and the detail section
    parts = digest.split("---\n", 2)
    overview = parts[0] if len(parts) > 0 else ""
    detail = parts[2] if len(parts) > 2 else ""

    overview_text = _markdown_to_feishu_text(overview)

    success_count = 0

    def _send(text: str) -> bool:
        body = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if FEISHU_SECRET:
            import hmac
            import hashlib
            import base64
            ts = str(int(datetime.now().timestamp()))
            key = FEISHU_SECRET.encode()
            msg = f"{ts}\n{FEISHU_SECRET}".encode()
            h = hmac.new(key, msg, hashlib.sha256)
            body["timestamp"] = ts
            body["sign"] = base64.b64encode(h.digest()).decode()

        resp = requests.post(FEISHU_WEBHOOK_URL, json=body, timeout=15)
        return resp.json().get("code") == 0

    try:
        # message 1: overview
        if _send(overview_text):
            success_count += 1
        else:
            print("[publish] Feishu overview failed")

        # message 2: full detail
        if detail.strip():
            detail_text = _markdown_to_feishu_text(detail.strip())
            chunks = [detail_text[i:i+25000] for i in range(0, len(detail_text), 25000)]
            for ci, chunk in enumerate(chunks):
                suffix = "\n\n... (接下文)" if ci < len(chunks)-1 else ""
                if _send(chunk + suffix):
                    success_count += 1

        # messages 3+: social media copy-paste posts
        if posts_map:
            for article_id, platforms in posts_map.items():
                for platform in ("xiaohongshu", "douyin"):
                    content = platforms.get(platform, "")
                    if not content:
                        continue
                    label = {"xiaohongshu": "小红书", "douyin": "抖音"}[platform]
                    header = f"――――――――――\n【{label}文案 - 复制发布】\n――――――――――\n\n"
                    full = header + content
                    if _send(full):
                        success_count += 1
                        print(f"[publish] Feishu {platform} post sent for {article_id[:20]}")
                    # small delay between messages to keep order
                    import time
                    time.sleep(0.3)
    except Exception as e:
        print(f"[publish] Feishu failed: {e}")
        return False

    print(f"[publish] Feishu sent {success_count} messages")
    return True


# ─── File export for manual review ──────────────────────

def save_manual_posts(posts_map: dict):
    """Save social media posts as individual files for manual review/publishing."""
    if not posts_map:
        return

    manual_dir = OUTPUT_DIR / "manual_review"
    manual_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

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
    today = datetime.now().strftime("%Y%m%d")

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

    # 1. Feishu - instant push (domestic priority, includes social posts)
    results["feishu"] = publish_feishu(digest, posts_map)

    # 2. Telegram - instant push
    results["telegram"] = publish_telegram_digest(digest)

    # 3. WordPress - draft (safe, won't auto-publish)
    today = datetime.now().strftime("%Y-%m-%d")
    title = f"AI/科技早报 | {today}"
    wp_preview = digest[:3000] + "\n\n...\n\n[完整版见公众号]"
    results["wordpress"] = publish_wordpress(title, wp_preview, status="draft")

    # 3. Save for manual review (WeChat, XHS, Zhihu)
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
