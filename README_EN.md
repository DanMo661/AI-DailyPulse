<div align="center">
  <img src="assets/banner.svg" alt="AI DailyPulse" width="100%">

  [![CI](https://github.com/DanMo661/AI-DailyPulse/actions/workflows/daily-digest.yml/badge.svg)](https://github.com/DanMo661/AI-DailyPulse/actions/workflows/daily-digest.yml)
  [![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
  [![License: MIT](https://img.shields.io/badge/license-MIT-3fb950.svg)](LICENSE)

  **Fully-automated AI tech digest** — collects from Hacker News / ArXiv / dev.to / tech RSS feeds,
  curates and rewrites with an LLM, then publishes to Feishu / Telegram / WordPress and drafts
  posts for WeChat / Xiaohongshu / Zhihu / Douyin.

  Fork it, add a couple of secrets, done. Runs **free on GitHub Actions** — zero servers.

  [简体中文](./README.md) | [English](./README_EN.md)
</div>

---

## What it does every day

Two editions daily at **00:00 / 12:00 UTC**, entirely inside GitHub Actions:

| Step | What happens |
|---|---|
| 📡 Collect | Fetches ~30 articles in parallel from HN, ArXiv (cs.AI), dev.to, hnrss, TechCrunch, Simon Willison, lobste.rs; dedupes by URL |
| 🔍 Filter | LLM judges each article: rejects marketing noise, writes a Chinese headline + key points for the rest |
| 📝 Curate | One "editor-in-chief" call picks **1 headline story** (120–180 character paragraph) + **4 notable picks** |
| 🖼️ Cover | Grabs the headline article's `og:image` as the cover, archived to `covers/` |
| 📣 Rewrite | Headline is rewritten into 5 platform-specific posts (WeChat / Xiaohongshu / Zhihu / Telegram / Douyin) |
| 🚀 Publish | Feishu (one message) · Telegram (per-section) · WordPress (draft) · rest saved as files for manual posting |

Guardrails: if ≥ 50% of the per-article filter calls fail, the edition aborts (better no issue than a broken one); a missing cover never blocks the pipeline.

## Example output (real, not staged)

> ### Claude Fable 5.1 released, strong new benchmark scores
>
> Anthropic shipped Claude Fable 5.1 today, scoring 52.6% on the Terminal-Bench-Science 0.1 benchmark, with official claims of significant gains in coding and knowledge work…
>
> **📌 Also notable**
> 1. **Claude's new system prompt guards against lyric reproduction** — Anthropic published Claude's consumer-app system prompt and its change history, adding an explicit ban on reproducing song lyrics to reduce copyright risk.
> 2. **CERN migrates industrial computers from RHEL to Debian** — after years on RHEL, CERN announced a move to Debian for its industrial computing fleet.
> 3. **Python 3.15 release candidate 2 is out** — the release enters hardening mode, bug-fixes only, final due in October.
>
> *(Excerpt — full issue in [docs/example_digest.md](docs/example_digest.md), written in Chinese as the target audience is Chinese developers.)*

## Quick start (5 minutes)

```bash
# No server required — just a GitHub account and an OpenAI-compatible API key
```

1. **Fork this repo**
2. In your fork: **Settings → Secrets and variables → Actions**, add secrets:

   | Secret | Required | Notes |
   |---|---|---|
   | `LLM_API_KEY` | ✅ | Any OpenAI-compatible provider: DeepSeek / OpenAI / OrcaRouter / SiliconFlow… |
   | `LLM_BASE_URL` | optional | Defaults to `https://api.deepseek.com`; OrcaRouter: `https://api.orcarouter.ai/v1` |
   | `LLM_MODEL` | optional | Defaults to `deepseek-chat`; OrcaRouter example: `deepseek/deepseek-chat` |
   | `FEISHU_WEBHOOK_URL` + `FEISHU_SECRET` | channel | Feishu group bot webhook |
   | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHANNEL` | channel | Telegram channel push |
   | `WP_URL` + `WP_USER` + `WP_APP_PASSWORD` | channel | WordPress (saves as **draft**, never auto-publishes) |

3. Open the **Actions** tab, enable the workflow (GitHub disables schedules on forks by default), then trigger **Run workflow** once to verify
4. Done — issues go out automatically at 00:00 / 12:00 UTC

**Cost**: ~35 LLM calls per edition (30 per-article passes + 1 editor pass + 5 platform rewrites). On DeepSeek's official API that's single-digit cents; free-tier models bring it to zero.

### Run locally (optional)

```bash
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env    # put your LLM_API_KEY in
python src/main.py                    # full pipeline
python src/main.py --collect-only     # collect only, no LLM usage
```

## Publishing channels

| Channel | Method | Automation |
|---|---|---|
| Feishu | Group bot webhook, whole issue in one message | Fully automatic |
| Telegram | Bot API, one message per section | Fully automatic |
| WordPress | REST API draft (human review before publishing) | Fully automatic |
| WeChat / Zhihu / Douyin | Generated posts saved to `output/manual_review/` | Manual posting |
| Xiaohongshu | Posts saved as files; experimental Playwright semi-auto script | Local script |

## Customization

- **Sources**: `SOURCES` / `RSS_FEEDS` in `src/config.py` — any RSS feed works
- **Schedule**: cron in `.github/workflows/daily-digest.yml`
- **Editorial taste & writing style**: the prompts in `src/process.py`
- **Issue size**: `MAX_TOTAL_ARTICLES` in `src/config.py`

## FAQ

**Is my API key safe?**
Keys live only in your fork's GitHub Secrets. The pipeline calls only the provider you configured — no third-party relay.

**Why does WordPress only save drafts?**
Human review before publishing AI-generated content — good for your readers and your domain.

**What if a day has nothing worth posting?**
It's treated as a normal quiet day: nothing is published, no error raised. Cross-run dedup uses `data/seen_urls.json` persisted via the Actions cache.

**Schedule not running after forking?**
GitHub disables scheduled workflows on forks by default — enable once in the Actions tab. Also, schedules auto-pause after 60 days of repo inactivity; re-enabling fixes it.

**Disclaimer**
The Xiaohongshu script uses unofficial automation and carries platform-risk; review AI-generated content before posting and follow each platform's terms of service.

## License

[MIT](LICENSE)
