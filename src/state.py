"""Cross-run state: seen-article memory + the pending article pool.

data/seen_urls.json — md5 ids of every URL ever fetched (newest last, capped),
                      so an article is never collected twice.
data/pool.json      — articles collected but not yet published (v3 batch mode).
                      The publish job digests the whole pool, then clears it
                      only after Feishu confirms delivery.
"""

import json

from config import (
    MAX_POOL_SIZE,
    POOL_FILE,
    SEEN_URLS_FILE,
)


def load_seen() -> list:
    """Load seen article ids, preserving order (oldest first)."""
    if SEEN_URLS_FILE.exists():
        return json.loads(SEEN_URLS_FILE.read_text(encoding="utf-8"))
    return []


def save_seen(seen: list):
    # keep newest 5000 to avoid unbounded growth (list is insertion-ordered)
    SEEN_URLS_FILE.write_text(json.dumps(seen[-5000:], ensure_ascii=False), encoding="utf-8")


def load_pool() -> list:
    if POOL_FILE.exists():
        return json.loads(POOL_FILE.read_text(encoding="utf-8"))
    return []


def save_pool(pool: list):
    POOL_FILE.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")


def append_to_pool(articles: list) -> list:
    """Add batch articles to the pool (dedupe by id), cap size keeping newest.

    Returns the updated pool.
    """
    pool = load_pool()
    have = {a["id"] for a in pool}
    for a in articles:
        if a["id"] not in have:
            pool.append(a)
            have.add(a["id"])
    pool.sort(key=lambda x: x.get("fetched_at", ""), reverse=True)
    pool = pool[:MAX_POOL_SIZE]
    save_pool(pool)
    return pool


def clear_pool():
    save_pool([])
