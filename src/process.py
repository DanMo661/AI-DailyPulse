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


def process_articles(articles: list[dict]) -> list[dict]:
    """Filter + summarize each article in a single LLM call, drop irrelevant ones."""
    kept = []
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
            a["digest"] = _fallback_digest(a)
        kept.append(a)
    print(f"[process] filtered: {len(articles)} → {len(kept)}")
    return kept


# ─── Step 2: Multi-style Rewrite ────────────────────────

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

REWRITE_TOP_N = 5
REWRITE_MIN_SCORE = 0.6


def generate_social_posts(article: dict) -> dict:
    """Generate multi-platform social media posts for one article."""
    digest = article.get("digest", {})
    content = f"""标题(英): {article['title']}
标题(中): {digest.get('title_cn', '')}
要点: {json.dumps(digest.get('key_points', []), ensure_ascii=False)}
一句话: {digest.get('one_liner', '')}
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


# ─── Step 3: Period Overview ────────────────────────────

def generate_overview(articles: list[dict]) -> str:
    """Generate a period overview identifying major/breaking news."""
    if not articles:
        return ""

    summaries = []
    for a in articles:
        d = a.get("digest", {})
        title = d.get("title_cn", a["title"])
        one = d.get("one_liner", "")
        if one:
            summaries.append(f"- {title}：{one}")
        else:
            summaries.append(f"- {title}")

    summary_text = "\n".join(summaries[:12])

    system = "你是一个科技新闻主编。分析以下本期科技新闻，输出一段中文概览（150字以内）。"
    user = f"""以下是本期科技新闻：

{summary_text}

请写一段概览，包含：
1. 本期整体发生了什么
2. 如果有重磅/突破性消息，重点指出来（没有就不写）

要求：自然段落，不要列表，不要编号，不要 emoji。"""

    try:
        result = _chat(system, user, temperature=0.3, max_tokens=500)
        print(f"[process] overview generated ({len(result)} chars)")
        return result
    except Exception as e:
        print(f"[process] overview error (skipping): {e}")
        return ""


# ─── Step 4: Assemble Daily Digest ──────────────────────

def assemble_digest(articles: list[dict], overview: str = "") -> str:
    """Assemble all summaries into a daily digest markdown."""
    today = datetime.now(BEIJING_TZ).strftime("%Y年%m月%d日")

    # overview section
    overview_section = ""
    if overview:
        overview_section = f"## 📋 本期概览\n\n{overview}\n\n---\n\n"

    # each article: brief summary
    entries = []
    for a in articles:
        d = a.get("digest", {})
        title_cn = d.get("title_cn", a["title"])
        one_liner = d.get("one_liner", "")
        points = [p.rstrip("。").rstrip(".").strip() for p in d.get("key_points", []) if p and p.strip()]

        if points:
            # deduplicate: if one_liner is essentially the same as first key_point, skip it
            one = one_liner.rstrip("。").rstrip(".").strip()
            if one and one not in points[0] and points[0] not in one:
                para = f"{one}。{points[0]}。"
            elif one:
                para = f"{one}。"
            else:
                para = f"{points[0]}。"
        else:
            para = (one_liner or "暂无摘要").rstrip("。").strip() + "。"

        entries.append(
            f"### {title_cn}\n\n"
            f"{para}\n\n"
            f"来源: {a['source']}  |  [原文链接]({a['url']})\n"
        )

    digest = (
        f"# 🤖 AI/科技文摘 | {today}\n\n"
        f"{overview_section}"
        + "\n---\n".join(entries)
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
    articles = process_articles(articles)
    if not articles:
        print("[process] all articles filtered out")
        return None

    # Step 2: multi-style posts for top articles
    posts_map = {}
    for i, a in enumerate(articles[:REWRITE_TOP_N]):
        if a.get("digest", {}).get("relevance_score", 0) > REWRITE_MIN_SCORE:
            print(f"[process] rewriting {i+1}: {a['digest'].get('title_cn', '')[:40]}")
            posts_map[a["id"]] = generate_social_posts(a)

    # Step 3: generate period overview
    overview = generate_overview(articles)

    # Step 4: assemble digest
    digest = assemble_digest(articles, overview)
    DIGEST_OUTPUT.write_text(digest, encoding="utf-8")
    print(f"[process] digest written to {DIGEST_OUTPUT}")

    # Save social posts
    SOCIAL_OUTPUT.write_text(
        json.dumps(posts_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"digest": digest, "posts": posts_map, "article_count": len(articles)}


if __name__ == "__main__":
    result = process_all()
    if result:
        print(f"\n[process] done: {result['article_count']} articles processed")
