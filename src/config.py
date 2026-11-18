import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# load .env file if present
_env_file = ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def env_str(key: str, default: str = "") -> str:
    """Read env var, falling back to default when unset OR empty.

    Empty must fall back too: GitHub Actions sets empty env vars for
    secrets that don't exist, which once produced a blank LLM_BASE_URL
    and broke every LLM call in the pipeline.
    """
    return os.environ.get(key, "").strip() or default


DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# China has no DST, fixed offset avoids the tzdata dependency on Windows
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

# --- LLM ---
# Any OpenAI-compatible provider. LLM_* names are preferred; DEEPSEEK_* work
# as legacy aliases so existing secrets keep working without changes.
# OrcaRouter: LLM_BASE_URL=https://api.orcarouter.ai/v1, LLM_MODEL=deepseek/deepseek-chat
LLM_API_KEY = env_str("LLM_API_KEY") or env_str("DEEPSEEK_API_KEY")
LLM_BASE_URL = env_str("LLM_BASE_URL") or env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = env_str("LLM_MODEL", "deepseek-chat")

# --- Content Sources ---
SOURCES = {
    "hn_top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "devto": "https://dev.to/api/articles?top=10",
    "arxiv_cs_ai": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=lastUpdatedDate&max_results=5",
}

# Reddit removed: it returns 403 HTML to CI runner IPs, so those sources
# yielded 0 articles on every scheduled run.
# 机器之心 removed: /rss returns an HTML page since ~2026-10 (verified dead).
# VentureBeat removed: AI feed returned 0 entries (verified dead 2026-11-18).
# Order matters: batch selection round-robins across sources in this order.
RSS_FEEDS = [
    "https://www.qbitai.com/feed",                # 量子位，中文 AI 媒体
    "https://techcrunch.com/feed/",
    "https://simonwillison.net/atom/everything/",  # highest-signal AI blog
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.technologyreview.com/feed/",
    "https://lobste.rs/rss",  # replaces r/programming
    "https://hnrss.org/frontpage?count=10",  # HN second channel (dedup vs hn_top)
]

# AIHOT (aihot.news, 卡兹克) — public agent API, anonymous, ~60 req/min limit.
# Pre-filtered Chinese AI news: zh title + AI digest + original-article link
# + 0-100 score. No image fields (covers still come from og:image).
AIHOT_API_URL = "https://aihot.news/api/v1/items"
AIHOT_WINDOW = "24h"
AIHOT_LIMIT = 50

MAX_ARTICLES_PER_SOURCE = 10
MAX_TOTAL_ARTICLES = 30

# --- v3 batch collection ---
# v3 cadence: 4 collection batches a day (14:00/20:02/02:00/07:50 Beijing),
# each appends BATCH_SIZE articles to the pending pool; the last batch runs
# inside the publish job which then digests the whole pool.
BATCH_SIZE = 10
MAX_POOL_SIZE = 60

# Parallel per-article LLM filter workers. Keep low: free-tier providers
# (e.g. OrcaRouter -free) 429 aggressively under concurrency.
FILTER_WORKERS = int(env_str("LLM_FILTER_WORKERS", "2"))

# --- Publishing ---
TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = env_str("TELEGRAM_CHANNEL")

WP_URL = env_str("WP_URL")
WP_USER = env_str("WP_USER")
WP_APP_PASSWORD = env_str("WP_APP_PASSWORD")

# Feishu bot
FEISHU_WEBHOOK_URL = env_str("FEISHU_WEBHOOK_URL")
FEISHU_SECRET = env_str("FEISHU_SECRET")

# --- Runtime ---
SEEN_URLS_FILE = DATA_DIR / "seen_urls.json"
RAW_ARTICLES_FILE = DATA_DIR / "raw_articles.json"
POOL_FILE = DATA_DIR / "pool.json"
DIGEST_OUTPUT = OUTPUT_DIR / "digest.md"
SOCIAL_OUTPUT = OUTPUT_DIR / "social_posts.json"

# v3 digest format: every article (headline + picks) ends with its link on
# its own paragraph, prefixed like this — plain URL so the digest is
# copy-paste friendly (used by process.assemble_digest and wechat.py).
LINK_PREFIX = "原文链接："


def validate_config() -> None:
    """Fail fast with a clear message when required config is missing."""
    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY (or legacy DEEPSEEK_API_KEY)")
    if missing:
        raise SystemExit(
            "[config] missing required env vars: "
            + ", ".join(missing)
            + " — set them in .env (local) or repo secrets (CI)"
        )
