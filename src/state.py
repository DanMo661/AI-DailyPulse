"""Cross-run state: seen-article memory + the pending article pool.

data/seen_urls.json — md5 ids of every URL ever fetched (newest last, capped),
                      so an article is never collected twice.
data/pool.json      — articles collected but not yet published (v3 batch mode).
                      The publish job digests the whole pool, then clears it
                      only after Feishu confirms delivery.

Corrupt files are quarantined (renamed *.corrupt) instead of crashing every
future run — data/ rides the actions/cache, so an unhandled JSONDecodeError
here would poison the pipeline until someone manually repairs the cache.
"""

import json

from config import (
    MAX_POOL_SIZE,
    POOL_FILE,
    SEEN_URLS_FILE,
)


def _load_json_list(path) -> list:
    """Load a JSON list file; quarantine corrupt files and start fresh."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        corrupt = path.with_suffix(path.suffix + ".corrupt")
        path.rename(corrupt)
        print(f"[state] WARNING: {path.name} was corrupt ({e}); "
              f"quarantined as {corrupt.name}, starting fresh. "
              f"seen 丢失=可能重推旧文一期；pool 丢失=今日早刊素材减少。")
        return []


def load_seen() -> list:
    """Load seen article ids, preserving order (oldest first)."""
    return _load_json_list(SEEN_URLS_FILE)


def save_seen(seen: list):
    # keep newest 5000 to avoid unbounded growth (list is insertion-ordered)
    SEEN_URLS_FILE.write_text(json.dumps(seen[-5000:], ensure_ascii=False), encoding="utf-8")


def load_pool() -> list:
    return _load_json_list(POOL_FILE)


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
