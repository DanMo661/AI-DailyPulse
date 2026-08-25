import json
from datetime import datetime

from openai import OpenAI

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    BEIJING_TZ,
    RAW_ARTICLES_FILE,
    DIGEST_OUTPUT,
    SOCIAL_OUTPUT,
)

_client = None


def _get_client() -> OpenAI:
    """Lazy client: created on first LLM call, so --collect-only works without a key."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def _chat(system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000, json_mode: bool = False) -> str:
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return resp.choices[0].message.content


def _parse_json(text: str) -> dict:
    """Parse a JSON object out of an LLM reply (with fence fallback)."""
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# ─── Step 1: Filter + Summarize (one LLM call per article) ──

DIGEST_PROMPT = """你是技术内容编辑兼分析师。先判断这篇文章是否值得收录到每日AI/科技文摘，值得则完成中文摘要。

拒绝标准(输出 relevant=false):
- 纯营销/广告/软文
- 与编程、AI、科技完全无关
- 纯八卦/娱乐，无信息量
- 重复的行情/价格播报

通过标准:
- 新的技术突破/研究发现
- 有用的工具/库/产品发布
- 有深度的技术分析/教程
- 行业重要动态/政策

通过时输出:
- title_cn: 中文标题(翻译+润色，保持原意，像新闻标题，≤25字)
- key_points: 最多2条，每条≤30字，只保留最核心信息
- one_liner: 一句话概括(≤30字)
- relevance_score: 0.0~1.0，越高越值得分享给国内开发者

规则: 不添加原文没有的信息；专业术语保留英文原名；涉及数字必须准确。

输出仅 JSON:
{"relevant": true, "reason": "一句话理由", "title_cn": "中文标题", "key_points": ["要点1", "要点2"], "one_liner": "一句话概括", "relevance_score": 0.8}"""


def _fallback_digest(article: dict) -> dict:
    return {
        "title_cn": article["title"],
        "key_points": [article.get("summary", "")[:60]],
        "one_liner": article["title"],
        "relevance_score": 0.5,
    }


def process_articles(articles: list[dict]) -> tuple[list[dict], int]:
    """Filter + summarize each article in a single LLM call, drop irrelevant ones.

    Returns (kept_articles, error_count). A failed call keeps the article with a
    fallback digest; the caller decides whether the error ratio is acceptable.
    """
    kept = []
    errors = 0
    for i, a in enumerate(articles):
        print(f"[process] digesting {i+1}/{len(articles)}: {a['title'][:50]}")
        text = f"标题: {a['title']}\n来源: {a['source']}\n摘要: {a.get('summary', '')[:1500]}"
        try:
            data = _parse_json(_chat(DIGEST_PROMPT, text, temperature=0.1, max_tokens=600, json_mode=True))
            if not data.get("relevant"):
                continue
            a["filter_reason"] = data.get("reason", "")
            points = [str(p) for p in (data.get("key_points") or []) if str(p).strip()]
            a["digest"] = {
                "title_cn": str(data.get("title_cn") or a["title"])[:50],
                "key_points": points[:2],
                "one_liner": str(data.get("one_liner") or "")[:60],
                "relevance_score": float(data.get("relevance_score") or 0.5),
            }
        except Exception as e:
            print(f"[process] digest error for '{a['title'][:40]}': {e}")
            # LLM failure shouldn't drop the article
            errors += 1
            a["digest"] = _fallback_digest(a)
        kept.append(a)
    print(f"[process] filtered: {len(articles)} → {len(kept)} ({errors} errors)")
    return kept, errors


# abort publishing when this fraction of LLM calls fails — a full API outage
# shouldn't push a digest full of fallback placeholders to channels
MAX_ERROR_RATIO = 0.5


# ─── Step 2: Finalize (one editor call → headline + 4 picks) ──

FINALIZE_PROMPT = """你是科技新闻主编，为每日 AI/科技早报定稿。

下面是一批候选文章的摘要（已筛过，含中文标题、要点、来源、原文链接）。请：

1. 选出本日最重磅、最值得头条的 1 篇：
   - headline_title: 抓人眼球的中文标题（≤25字，侧重重点，如"DeepSeek V4 正式版发布！"）
   - headline_paragraph: 120~180字正文，一句话点出新闻，再展开核心信息，自然段落，不列点
2. 另选 4 篇本日最值得关注的，按重要性从高到低排序，每篇：
   - title_cn: 中文标题（英文原文转中文，忠于原意）
   - blurb: 50字左右简介
   - url: 原文链接（必须引用下方候选中的 url，禁止编造）

链接规则: 头条与精选的链接优先选新闻站点/公司官网/官方博客；
x.com、twitter.com、reddit.com、youtube.com 等社交平台链接只能在没有更好来源时使用。

正文规则: 只基于候选摘要里已有的信息写作，不得编造具体数字、引语或原文没有的细节。

头条标准：重大突破/发布、行业大事件优先；教程、软文、普通产品体验不得当头条。

仅输出 JSON：
{"headline": {"url": "...", "headline_title": "...", "headline_paragraph": "..."},
 "items": [{"url": "...", "title_cn": "...", "blurb": "..."}]}
// items 恰好 4 条，不得包含头条，顺序即重要性降序"""


def _candidate_section(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        d = a.get("digest", {})
        lines.append(
            f"[{i}] 标题: {a['title']} | 中文: {d.get('title_cn', '')} | "
            f"要点: {'；'.join(d.get('key_points', []))} | 一句话: {d.get('one_liner', '')} | "
            f"来源: {a['source']} | 链接: {a['url']}"
        )
    return "\n".join(lines)


def finalize(articles: list[dict]) -> dict:
    """Pick the headline story + 4 picks from the candidates; sanitize the model output."""
    by_url = {a["url"]: a for a in articles}
    ranked = sorted(articles, key=lambda a: a.get("digest", {}).get("relevance_score", 0), reverse=True)

    def _fallback() -> dict:
        top = ranked[0]
        d = top["digest"]
        return {
            "headline": {
                "url": top["url"],
                "headline_title": d.get("title_cn", top["title"]),
                "headline_paragraph": f"{d.get('one_liner', '')}。{d.get('key_points', [''])[0]}",
            },
            "items": [],
        }

    try:
        data = _parse_json(_chat(
            FINALIZE_PROMPT, _candidate_section(articles),
            temperature=0.2, max_tokens=1200, json_mode=True,
        ))
    except Exception as e:
        print(f"[process] finalize error, using fallback picks: {e}")
        return _fallback()

    headline = dict(data.get("headline") or {})
    ha = by_url.get(str(headline.get("url", "")))
    if not ha:  # model invented a url — take the top-ranked candidate
        ha = ranked[0]
        headline["url"] = ha["url"]
    hd = ha["digest"]
    if not headline.get("headline_title"):
        headline["headline_title"] = hd.get("title_cn", ha["title"])
    if not headline.get("headline_paragraph"):
        headline["headline_paragraph"] = f"{hd.get('one_liner', '')}。{hd.get('key_points', [''])[0]}"

    items, seen_urls = [], {headline["url"]}
    for it in data.get("items") or []:
        url = str(it.get("url", ""))
        if url in seen_urls or url not in by_url:
            continue
        seen_urls.add(url)
        items.append({
            "url": url,
            "title_cn": str(it.get("title_cn") or by_url[url]["digest"].get("title_cn", ""))[:50],
            "blurb": str(it.get("blurb") or by_url[url]["digest"].get("one_liner", ""))[:80],
        })
        if len(items) == 4:
            break
    # fill missing picks from the ranking (prefer error-free LLM output but never starve the list)
    for a in ranked:
        if len(items) >= 4:
            break
        if a["url"] in seen_urls:
            continue
        seen_urls.add(a["url"])
        items.append({
            "url": a["url"],
            "title_cn": a["digest"].get("title_cn", a["title"])[:50],
            "blurb": a["digest"].get("one_liner", "")[:80],
        })

    return {"headline": headline, "items": items}


# ─── Step 3: Headline Rewrite (social posts) ────────────

STYLE_PROMPTS = {
    "wechat": """你是微信公众号科技编辑。将以下内容写成公众号推送段落。
风格: 专业简洁，中英术语混用，200-300字。开头直接说事，不要寒暄。
用 Markdown 格式，保留原文链接。不要标题（标题单独生成）。""",

    "xiaohongshu": """你是小红书科技博主。将以下内容写成小红书文案。

格式（严格执行）:
- 第1段：用一段话概括讲了什么（≤80字）
- 然后分点展开，每点用「 | 标题」开头，后跟1句解释
- 末尾加 3 个标签

规则:
- 全中文
- 口语化，适当 emoji
- ≤300字
- 有干货，不水""",

    "zhihu": """你是知乎科技领域答主。将以下内容写成知乎回答段落。
风格: 深度分析，有观点，400-600字。带引用格式标注来源。""",

    "telegram": """你是 Telegram 科技频道编辑。压缩为一条消息。
格式: 🔥 [中文标题]
📝 一句话要点
🔗 原文链接
不超过 150 字。简洁有力。""",

    "douyin": """你是抖音科技博主。写成抖音视频口播文案。
风格: 口语化，开头3秒必须有钩子。
文案区 ≤200字：第一段说事，第二段一句话引互动。
末尾加 3 个标签。
禁止书面语、禁止长难句。""",
}


def generate_headline_posts(headline: dict, article: dict) -> dict:
    """Generate multi-platform social posts for the headline story."""
    content = f"""头条标题: {headline['headline_title']}
正文介绍: {headline['headline_paragraph']}
要点: {json.dumps(article['digest'].get('key_points', []), ensure_ascii=False)}
来源: {article['source']}
原文: {article['url']}"""

    posts = {}
    for platform, prompt in STYLE_PROMPTS.items():
        try:
            posts[platform] = _chat(prompt, content, temperature=0.7, max_tokens=1500)
        except Exception as e:
            print(f"[process] {platform} rewrite error: {e}")
            posts[platform] = ""
    return posts


# ─── Step 4: Assemble Daily Digest ──────────────────────

def assemble_digest(headline: dict, items: list[dict], cover_file: str = "") -> str:
    """Assemble the blog-style digest: 1 headline story + a numbered pick list."""
    today = datetime.now(BEIJING_TZ).strftime("%Y年%m月%d日")

    cover_section = f"\n![封面]({cover_file})\n" if cover_file else ""

    list_entries = []
    for i, it in enumerate(items, 1):
        list_entries.append(
            f"{i}. **{it['title_cn']}**（[原文]({it['url']})）— {it['blurb'].rstrip('。')}。"
        )

    digest = (
        f"# 🤖 AI DailyPulse | {today}\n\n"
        f"## 🔥 今日头条\n\n"
        f"### {headline['headline_title']}\n\n"
        f"{headline['headline_paragraph'].rstrip('。')}。\n"
        f"{cover_section}\n"
        f"[原文链接]({headline['url']})\n\n"
        f"## 📌 其他重点\n\n"
        + "\n".join(list_entries)
        + "\n\n> 📬 AI 自动生成\n"
    )

    return digest


# ─── Orchestrator ───────────────────────────────────────

def process_all():
    """Run the full AI processing pipeline."""
    if not RAW_ARTICLES_FILE.exists():
        print("[process] no raw articles")
        return None

    articles = json.loads(RAW_ARTICLES_FILE.read_text(encoding="utf-8"))
    if not articles:
        print("[process] empty articles list")
        return None

    # Step 1: filter + summarize
    articles, errors = process_articles(articles)
    if errors and errors / len(articles) >= MAX_ERROR_RATIO:
        return {"abort": f"{errors}/{len(articles)} LLM calls failed (invalid API key or quota?)"}
    if not articles:
        print("[process] all articles filtered out")
        return None

    # Step 2: pick headline + 4 items
    final = finalize(articles)
    headline = final["headline"]
    items = final["items"]
    print(f"[process] headline: {headline['headline_title']} ({len(items)} picks)")

    # Step 3: social posts for the headline story only
    headline_article = next((a for a in articles if a["url"] == headline["url"]), articles[0])
    posts_map = {}
    if headline_article.get("digest", {}).get("relevance_score", 0) > 0.5:
        posts_map[headline_article["id"]] = generate_headline_posts(headline, headline_article)

    # Step 4: cover image from the headline article's site (never blocks the digest)
    cover_file = ""
    try:
        from cover import fetch_cover
        cover_file = fetch_cover(headline["url"]) or ""
    except Exception as e:
        print(f"[process] cover skipped: {e}")

    # Step 5: assemble blog-style digest
    digest = assemble_digest(headline, items, cover_file)
    DIGEST_OUTPUT.write_text(digest, encoding="utf-8")
    print(f"[process] digest written to {DIGEST_OUTPUT}")

    SOCIAL_OUTPUT.write_text(
        json.dumps(posts_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"digest": digest, "posts": posts_map, "article_count": len(articles)}


if __name__ == "__main__":
    result = process_all()
    if result:
        print(f"\n[process] done: {result['article_count']} articles processed")
