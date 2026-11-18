import hashlib
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import requests

from config import (
    AIHOT_API_URL,
    AIHOT_LIMIT,
    AIHOT_WINDOW,
    BATCH_SIZE,
    RSS_FEEDS,
    SOURCES,
    MAX_ARTICLES_PER_SOURCE,
    MAX_TOTAL_ARTICLES,
    RAW_ARTICLES_FILE,
)
from state import append_to_pool, load_seen, save_seen

# feedparser goes through urllib with no timeout of its own — a dead source
# would otherwise hang the whole batch (observed with lobste.rs)
socket.setdefaulttimeout(25)

_USER_AGENT = "Mozilla/5.0 (compatible; AI-DailyPulse/3.0; +https://github.com/DanMo661/AI-DailyPulse)"


def _md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def _make_id(url):
    return _md5(url)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ─── Fetchers ───────────────────────────────────────────

def fetch_aihot():
    """AIHOT (aihot.news) selected items via its public agent API — anonymous,
    no key, ~60 req/min limit. Pre-filtered Chinese AI news with zh titles,
    AI digests, original-article links and a 0-100 editor score."""
    articles = []
    try:
        resp = requests.get(
            AIHOT_API_URL,
            params={"mode": "selected", "window": AIHOT_WINDOW, "limit": AIHOT_LIMIT},
            headers={"User-Agent": _USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            url = (item.get("links") or {}).get("original", "")
            if not url:
                continue
            articles.append({
                "id": _make_id(url),
                "title": item.get("title", ""),
                "url": url,
                "summary": (item.get("summary") or "")[:800],
                "source": "AIHOT",
                "score": int(item.get("score") or 0),
                "fetched_at": _now_iso(),
            })
    except Exception as e:
        print(f"[collect] AIHOT failed: {e}")
    return articles


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
                        "fetched_at": _now_iso(),
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
                "fetched_at": _now_iso(),
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
                "fetched_at": _now_iso(),
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
                "fetched_at": _now_iso(),
            })
    except Exception as e:
        print(f"[collect] RSS {url} failed: {e}")
    return articles


def _build_tasks():
    """Task list in round-robin priority order: AIHOT and HN first, then the
    RSS list (config order, quality first), then the rest."""
    tasks = [
        ("aihot", fetch_aihot),
        ("hn", fetch_hn_top),
    ]
    for i, url in enumerate(RSS_FEEDS):
        tasks.append((f"rss{i}", lambda u=url: fetch_rss(u)))
    tasks.append(("devto", fetch_devto))
    tasks.append(("arxiv", fetch_arxiv))
    return tasks


def fetch_all() -> dict:
    """Fetch every source in parallel; return {task_name: [new articles]}
    (seen-filtered within each task, score-sorted)."""
    seen_set = set(load_seen())
    by_task = {}

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fn): name for name, fn in _build_tasks()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"[collect] {name} error: {e}")
                continue
            new = [a for a in result if a["id"] not in seen_set]
            new.sort(key=lambda x: x["score"], reverse=True)
            by_task[name] = new
            print(f"[collect] {name}: {len(new)} new articles")
    return by_task


def _round_robin(by_task: dict, limit: int) -> list:
    """Interleave task lists (one article per task per round, task order =
    priority) so no source crowds out another; skip cross-task URL dupes."""
    picked, picked_ids = [], set()
    cursors = {name: 0 for name in by_task}
    while len(picked) < limit:
        progressed = False
        for name, articles in by_task.items():
            if len(picked) >= limit:
                break
            i = cursors[name]
            while i < len(articles) and articles[i]["id"] in picked_ids:
                i += 1
            cursors[name] = i
            if i < len(articles):
                picked.append(articles[i])
                picked_ids.add(articles[i]["id"])
                cursors[name] = i + 1
                progressed = True
        if not progressed:
            break
    return picked


# ─── Orchestrators ──────────────────────────────────────

def collect_batch():
    """v3 batch mode: fetch everything, round-robin-pick BATCH_SIZE articles,
    append them to the pending pool. Marks every fetched article as seen so
    it never reappears in later batches. No LLM involved."""
    by_task = fetch_all()

    picked = _round_robin(by_task, BATCH_SIZE)

    seen = load_seen()
    seen_set = set(seen)
    for articles in by_task.values():
        for a in articles:
            if a["id"] not in seen_set:
                seen_set.add(a["id"])
                seen.append(a["id"])
    save_seen(seen)

    # batch snapshot for artifact upload / local replay
    RAW_ARTICLES_FILE.write_text(
        json.dumps(picked, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pool = append_to_pool(picked)
    print(f"[collect] batch: {len(picked)} picked, pool now {len(pool)}")
    return picked, pool


def collect_all():
    """Legacy one-shot mode (local `full`): fetch, dedupe, top-N by score."""
    by_task = fetch_all()

    seen = load_seen()
    seen_set = set(seen)
    all_articles = [a for articles in by_task.values() for a in articles]
    for a in all_articles:
        if a["id"] not in seen_set:
            seen_set.add(a["id"])
            seen.append(a["id"])
    save_seen(seen)

    all_articles.sort(key=lambda x: x["score"], reverse=True)
    all_articles = all_articles[:MAX_TOTAL_ARTICLES]

    RAW_ARTICLES_FILE.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[collect] total new: {len(all_articles)}")
    return all_articles


if __name__ == "__main__":
    picked, pool = collect_batch()
    for a in picked:
        title = a['title'][:80].encode('ascii', errors='replace').decode('ascii')
        print(f"  [{a['source']}] {title} (score={a['score']})")
