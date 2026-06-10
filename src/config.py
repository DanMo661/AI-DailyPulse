import os
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

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# --- LLM ---
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# --- Content Sources ---
SOURCES = {
    "hn_top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "hn_new": "https://hacker-news.firebaseio.com/v0/newstories.json",
    "reddit_programming": "https://www.reddit.com/r/programming/hot.json?limit=10",
    "reddit_machinelearning": "https://www.reddit.com/r/MachineLearning/hot.json?limit=10",
    "devto": "https://dev.to/api/articles?top=10",
    "arxiv_cs_ai": "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=lastUpdatedDate&max_results=5",
}

RSS_FEEDS = [
    "https://hnrss.org/frontpage?count=10",
    "https://techcrunch.com/feed/",
]

MAX_ARTICLES_PER_SOURCE = 10
MAX_TOTAL_ARTICLES = 30

# --- Publishing ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "")

WP_URL = os.environ.get("WP_URL", "")
WP_USER = os.environ.get("WP_USER", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

# WeChat Official Account
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")

# Resend email
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "")

# Feishu bot
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "")

# --- Runtime ---
SEEN_URLS_FILE = DATA_DIR / "seen_urls.json"
RAW_ARTICLES_FILE = DATA_DIR / "raw_articles.json"
DIGEST_OUTPUT = OUTPUT_DIR / "digest.md"
SOCIAL_OUTPUT = OUTPUT_DIR / "social_posts.json"
