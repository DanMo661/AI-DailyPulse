"""AI Digest Bot - Main Pipeline

Collect → Process → Publish

Usage:
    python src/main.py                # full pipeline
    python src/main.py --collect-only # only fetch articles
    python src/main.py --process-only # only process (needs raw_articles.json)
    python src/main.py --publish-only # only publish (needs digest.md + social_posts.json)

Environment variables required:
    DEEPSEEK_API_KEY        - DeepSeek API key
    DEEPSEEK_BASE_URL       - (optional) custom endpoint
    TELEGRAM_BOT_TOKEN      - (optional) Telegram bot token
    TELEGRAM_CHANNEL        - (optional) Telegram channel @name
    WP_URL / WP_USER / WP_APP_PASSWORD - (optional) WordPress
"""

import sys

from collect import collect_all
from process import process_all
from publish import publish_all
from config import DIGEST_OUTPUT, SOCIAL_OUTPUT


def main():
    args = set(sys.argv[1:])

    collect_only = "--collect-only" in args
    process_only = "--process-only" in args
    publish_only = "--publish-only" in args

    # default: run all
    run_all = not (collect_only or process_only or publish_only)

    if collect_only or run_all:
        print("=" * 50)
        print("  STEP 1: COLLECT")
        print("=" * 50)
        articles = collect_all()
        print(f"  Collected {len(articles)} new articles\n")

    if process_only or run_all:
        print("=" * 50)
        print("  STEP 2: PROCESS")
        print("=" * 50)
        result = process_all()
        if result:
            print(f"  Processed {result['article_count']} articles\n")

    if publish_only or run_all:
        print("=" * 50)
        print("  STEP 3: PUBLISH")
        print("=" * 50)
        import json
        digest = DIGEST_OUTPUT.read_text(encoding="utf-8") if DIGEST_OUTPUT.exists() else ""
        posts = {}
        if SOCIAL_OUTPUT.exists():
            posts = json.loads(SOCIAL_OUTPUT.read_text(encoding="utf-8"))
        results = publish_all(digest, posts)
        print(f"  Publish results: {results}\n")

    print("Pipeline complete.")


if __name__ == "__main__":
    main()
