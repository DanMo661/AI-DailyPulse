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

# --- LLM provider ---
# Two named providers share the same OpenAI-compatible wiring. DeepSeek is the
# default; setting ORCAROUTER_API_KEY opts the whole pipeline into OrcaRouter
# (an OpenAI-compatible AI gateway) without touching process.py, which only
# reads the resolved LLM_* values below.
ORCAROUTER_API_KEY = env_str("ORCAROUTER_API_KEY")
ORCAROUTER_BASE_URL = env_str("ORCAROUTER_BASE_URL", "https://api.orcarouter.ai/v1")
ORCAROUTER_MODEL = env_str("ORCAROUTER_MODEL", "orcarouter/auto")

if ORCAROUTER_API_KEY:
    LLM_API_KEY = ORCAROUTER_API_KEY
    LLM_BASE_URL = ORCAROUTER_BASE_URL
    LLM_MODEL = ORCAROUTER_MODEL
else:
    LLM_API_KEY = env_str("DEEPSEEK_API_KEY")
    LLM_BASE_URL = env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL = env_str("LLM_MODEL", "deepseek-chat")

# --- Content Sources ---
SOURCES = {
    "hn_top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "devto": "https://dev.to/api/articles?top=10",
    "arxiv_cs_ai": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=lastUpdatedDate&max_results=5",
}

# Reddit removed: it returns 403 HTML to CI runner IPs, so those sources
# yielded 0 articles on every scheduled run.
RSS_FEEDS = [
    "https://hnrss.org/frontpage?count=10",
    "https://techcrunch.com/feed/",
    "https://simonwillison.net/atom/everything/",  # highest-signal AI blog
    "https://lobste.rs/rss",  # replaces r/programming
]

MAX_ARTICLES_PER_SOURCE = 10
MAX_TOTAL_ARTICLES = 30

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
DIGEST_OUTPUT = OUTPUT_DIR / "digest.md"
SOCIAL_OUTPUT = OUTPUT_DIR / "social_posts.json"


def validate_config() -> None:
    """Fail fast with a clear message when required config is missing."""
    missing = []
    if not LLM_API_KEY:
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        raise SystemExit(
            "[config] missing required env vars: "
            + ", ".join(missing)
            + " — set them in .env (local) or repo secrets (CI)"
        )
