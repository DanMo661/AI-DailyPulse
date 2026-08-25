import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import requests

from config import (
    SOURCES,
    RSS_FEEDS,
    SEEN_URLS_FILE,
    RAW_ARTICLES_FILE,
    MAX_ARTICLES_PER_SOURCE,
    MAX_TOTAL_ARTICLES,
)


def load_seen() -> list:
    """Load seen article ids, preserving order (oldest first)."""
    if SEEN_URLS_FILE.exists():
        return json.loads(SEEN_URLS_FILE.read_text(encoding="utf-8"))
    return []


def save_seen(seen: list):
    # keep newest 5000 to avoid unbounded growth (list is insertion-ordered)
    SEEN_URLS_FILE.write_text(json.dumps(seen[-5000:], ensure_ascii=False), encoding="utf-8")


def _md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def _make_id(url):
    return _md5(url)


# ─── Fetchers ───────────────────────────────────────────

def fetch_hn_top():
    """Hacker News top stories."""
    articles = []
    try:
        ids = requests.get(SOURCES["hn_top"], timeout=15).json()[:MAX_ARTICLES_PER_SOURCE]
        for item_id in ids:
            try:
                item = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
                    timeout=10,
                ).json()
                if item and item.get("url"):
                    articles.append({
                        "id": _make_id(item["url"]),
                        "title": item.get("title", ""),
                        "url": item["url"],
                        "summary": item.get("text", "")[:500] if item.get("text") else "",
                        "source": "HackerNews",
                        "score": item.get("score", 0),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"[collect] HN top failed: {e}")
    return articles


def fetch_devto():
    """Fetch from Dev.to."""
    articles = []
    try:
        resp = requests.get(SOURCES["devto"], timeout=15)
        for post in resp.json()[:MAX_ARTICLES_PER_SOURCE]:
            articles.append({
                "id": _make_id(post["url"]),
                "title": post.get("title", ""),
                "url": post["url"],
                "summary": post.get("description", "")[:500],
                "source": "Dev.to",
                "score": post.get("positive_reactions_count", 0),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"[collect] Dev.to failed: {e}")
    return articles


def fetch_arxiv():
    """Fetch latest AI papers from ArXiv."""
    articles = []
    try:
        feed = feedparser.parse(SOURCES["arxiv_cs_ai"])
        for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
            articles.append({
                "id": _make_id(entry.link),
                "title": entry.title.strip(),
                "url": entry.link,
                "summary": entry.get("summary", "")[:500],
                "source": "ArXiv",
                "score": 0,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"[collect] ArXiv failed: {e}")
    return articles


def fetch_rss(url):
    """Fetch a generic RSS feed."""
    articles = []
    try:
        feed = feedparser.parse(url)
        source = feed.feed.get("title", url)
        for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
            link = entry.get("link", "")
            if not link:
                continue
            articles.append({
                "id": _make_id(link),
                "title": entry.get("title", ""),
                "url": link,
                "summary": entry.get("summary", entry.get("description", ""))[:500],
                "source": source,
                "score": 0,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"[collect] RSS {url} failed: {e}")
    return articles


# ─── Orchestrator ───────────────────────────────────────

def collect_all():
    """Fetch from all sources in parallel, deduplicate, return top articles."""
    seen = load_seen()
    seen_set = set(seen)
    all_articles = []

    tasks = [
        ("hn", fetch_hn_top),
        ("devto", fetch_devto),
        ("arxiv", fetch_arxiv),
    ]
    for url in RSS_FEEDS:
        tasks.append((f"rss:{url[:40]}", lambda u=url: fetch_rss(u)))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                all_articles.extend(result)
                print(f"[collect] {name}: {len(result)} articles")
            except Exception as e:
                print(f"[collect] {name} error: {e}")

    # dedup + filter seen
    new_articles = []
    for a in all_articles:
        if a["id"] not in seen_set:
            new_articles.append(a)
            seen_set.add(a["id"])
            seen.append(a["id"])

    # sort by score desc
    new_articles.sort(key=lambda x: x["score"], reverse=True)
    new_articles = new_articles[:MAX_TOTAL_ARTICLES]

    # save
    RAW_ARTICLES_FILE.write_text(
        json.dumps(new_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_seen(seen)

    print(f"[collect] total new: {len(new_articles)}")
    return new_articles


if __name__ == "__main__":
    articles = collect_all()
    for a in articles:
        title = a['title'][:80].encode('ascii', errors='replace').decode('ascii')
        print(f"  [{a['source']}] {title} (score={a['score']})")
