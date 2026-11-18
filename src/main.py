"""AI DailyPulse - Main Pipeline

v3 batch cadence (4 collection runs a day, one publish):

    python src/main.py collect              # one batch -> pending pool (no LLM, no push)
    python src/main.py publish [--dry-run]  # final batch + digest pool + push + clear pool
    python src/main.py full [--dry-run]     # legacy one-shot collect->process->publish

Exit codes: 0 = ok (including a normal empty day), 1 = must-retry failure
(LLM outage abort / Feishu delivery failed). The CI fallback trigger relies
on exit 1 + the pool staying intact to re-run 30 minutes later.

Environment variables required:
    LLM_API_KEY (or legacy DEEPSEEK_API_KEY) - OpenAI-compatible key
    LLM_BASE_URL / LLM_MODEL - (optional) provider override
    FEISHU_WEBHOOK_URL / FEISHU_SECRET - (optional) Feishu bot
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL - (optional) Telegram
    WP_URL / WP_USER / WP_APP_PASSWORD - (optional) WordPress
"""

import sys

from collect import collect_all, collect_batch
from config import validate_config
from process import process_pool
from publish import publish_all
from state import clear_pool, load_pool


def _finish_publish(result: dict, dry_run: bool) -> int:
    """Push the processed result; clear the pool only on confirmed delivery."""
    ok = _run_publish(result["digest"], result["posts"], dry_run)
    if not ok:
        print("  Feishu delivery failed — pool kept for the fallback retry.")
        return 1
    if not dry_run:
        clear_pool()
    return 0


def _run_publish(digest: str, posts: dict, dry_run: bool) -> bool:
    if dry_run:
        print("  [dry-run] skipping real push, writing artifacts only\n")
        results = publish_all(digest, posts, dry_run=True)
        print(f"  Publish results: {results}\n")
        return True
    results = publish_all(digest, posts)
    print(f"  Publish results: {results}\n")
    return bool(results.get("feishu"))


def cmd_collect() -> int:
    collect_batch()
    return 0


def cmd_publish(dry_run: bool) -> int:
    validate_config()  # fail fast before wasting a network collection run
    collect_batch()  # the day's final batch joins the pool before digesting
    pool = load_pool()
    if not pool:
        print("  Pool empty — nothing to publish (normal day).")
        return 0

    result = process_pool(pool)
    if result and "abort" in result:
        print(f"Pipeline aborted: {result['abort']}")
        return 1
    if not result:
        print("  Everything filtered out — clearing pool, nothing to publish.")
        clear_pool()
        return 0
    return _finish_publish(result, dry_run)


def cmd_full(dry_run: bool) -> int:
    validate_config()
    articles = collect_all()
    if not articles:
        print("  Nothing collected — skipping publish (normal day).")
        return 0

    result = process_pool(articles)
    if result and "abort" in result:
        print(f"Pipeline aborted: {result['abort']}")
        return 1
    if not result:
        print("  Everything filtered out — nothing to publish.")
        return 0
    return _finish_publish(result, dry_run)


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    command = next((a for a in args if not a.startswith("-")), "")

    handlers = {
        "collect": lambda: cmd_collect(),
        "publish": lambda: cmd_publish(dry_run),
        "full": lambda: cmd_full(dry_run),
    }
    handler = handlers.get(command)
    if handler is None:
        print(__doc__)
        sys.exit(2)
    sys.exit(handler())


if __name__ == "__main__":
    main()
