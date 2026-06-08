import json
from datetime import datetime, timezone

from openai import OpenAI
from pydantic import BaseModel

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    RAW_ARTICLES_FILE,
    DIGEST_OUTPUT,
    SOCIAL_OUTPUT,
)

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


class ArticleDigest(BaseModel):
    title_cn: str
    key_points: list[str]
    one_liner: str
    relevance_score: float


class SocialPosts(BaseModel):
    wechat: str
    xiaohongshu: str
    zhihu: str
    telegram: str


def _chat(system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000) -> str:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


# ─── Step 1: Relevance Filter ───────────────────────────

FILTER_PROMPT = """你是技术内容编辑。判断这篇文章是否值得收录到每日AI/科技文摘。

拒绝标准:
- 纯营销/广告/软文
- 与编程、AI、科技完全无关
- 纯八卦/娱乐，无信息量
- 重复的行情/价格播报

通过标准:
- 新的技术突破/研究发现
- 有用的工具/库/产品发布
- 有深度的技术分析/教程
- 行业重要动态/政策

输出仅 JSON: {"relevant": true/false, "reason": "一句话理由"}"""


def filter_articles(articles: list[dict]) -> list[dict]:
    """Filter articles by relevance, keep only the good ones."""
    kept = []
    for a in articles:
        try:
            text = f"标题: {a['title']}\n来源: {a['source']}\n摘要: {a.get('summary', '')[:300]}"
            result = _chat(FILTER_PROMPT, text, temperature=0.0, max_tokens=100)
            # try to parse JSON from the response
            result = result.strip()
            if "```" in result:
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            data = json.loads(result)
            if data.get("relevant"):
                a["filter_reason"] = data.get("reason", "")
                kept.append(a)
        except Exception as e:
            print(f"[process] filter error for '{a['title'][:40]}': {e}")
            # if filter fails, keep the article
            kept.append(a)
    print(f"[process] filtered: {len(articles)} → {len(kept)}")
    return kept


# ─── Step 2: Summarize ──────────────────────────────────

SUMMARY_PROMPT = """你是技术内容分析师。用中文总结以下文章。

输出 JSON:
{
  "title_cn": "中文标题（翻译+润色，保持原意）",
  "key_points": ["要点1(≤60字)", "要点2(≤60字)", "要点3(≤60字)"],
  "one_liner": "一句话概括（≤40字）",
  "relevance_score": 0.0~1.0 的分数（越高越值得分享给国内开发者）
}

规则:
- 不要添加原文没有的信息
- 专业术语保留英文原名
- 涉及数字/数据必须准确"""


def summarize_article(article: dict) -> dict:
    """Summarize a single article with structured output."""
    text = f"标题: {article['title']}\n来源: {article['source']}\n内容: {article.get('summary', '')[:2000]}"
    try:
        result = _chat(SUMMARY_PROMPT, text, temperature=0.1, max_tokens=600)
        result = result.strip()
        if "```" in result:
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        data = json.loads(result)
        article["digest"] = data
    except Exception as e:
        print(f"[process] summarize error for '{article['title'][:40]}': {e}")
        article["digest"] = {
            "title_cn": article["title"],
            "key_points": [article.get("summary", "")[:60]],
            "one_liner": article["title"],
            "relevance_score": 0.5,
        }
    return article


# ─── Step 3: Multi-style Rewrite ────────────────────────

STYLE_PROMPTS = {
    "wechat": """你是微信公众号科技编辑。将以下内容写成公众号推送段落。
风格: 专业但不生硬，中英术语混用，300-500字。开头吸引人，中间展开要点，结尾引导关注。
用 Markdown 格式，保留原文链接。不要标题（标题单独生成）。""",

    "xiaohongshu": """你是小红书科技博主。将以下内容写成小红书文案。
风格: 口语化中文，像朋友聊天，带 emoji。≤500字。开头用"最近发现..."这类自然引入。
加 3-5 个相关标签。不要标题党，内容要有干货。""",

    "zhihu": """你是知乎科技领域答主。将以下内容写成知乎回答/文章段落。
风格: 深度分析视角，有观点有论据，800-1200字。带引用格式标注来源。
可以补充背景知识帮助理解，但核心技术细节不能编造。""",

    "telegram": """你是 Telegram 科技频道的编辑。将以下内容压缩为一条 Telegram 消息。
格式: 🔥 [中文标题]
📝 一句话要点
🔗 原文链接
不超过 200 字。简洁有力。""",
}


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


# ─── Step 4: Assemble Daily Digest ──────────────────────

DIGEST_PROMPT = """你是技术文摘主编。将以下多条技术摘要整合成一份《每日 AI/科技早报》。

格式要求（Markdown）:

# 🤖 AI/科技早报 | {date}

## 今日速览
{3-5条一句话新闻，每条以 🔹 开头}

---
{每条重点新闻一个二级标题，包含: 中文标题、英文原标题、来源、3个要点、原文链接}

---
> 📬 由 AI 自动生成并人工审核。如有错误请联系修正。

风格: 信息密度高，专业但不枯燥。"""


def assemble_digest(articles: list[dict], posts_map: dict) -> str:
    """Assemble all summaries into a daily digest markdown."""
    today = datetime.now().strftime("%Y年%m月%d日")

    items = []
    for a in articles:
        d = a.get("digest", {})
        items.append({
            "title_en": a["title"],
            "title_cn": d.get("title_cn", a["title"]),
            "source": a["source"],
            "url": a["url"],
            "key_points": d.get("key_points", []),
            "one_liner": d.get("one_liner", ""),
            "score": a.get("score", 0),
        })

    # top articles for quick view
    top_one_liners = "\n".join(
        f"🔹 {it['one_liner']} — *{it['source']}*"
        for it in items[:5]
        if it["one_liner"]
    )

    # full entries
    entries = []
    for it in items:
        points = "\n".join(f"- {p}" for p in it["key_points"])
        entries.append(
            f"## {it['title_cn']}\n"
            f"*{it['title_en']}* | 来源: {it['source']}\n\n"
            f"{points}\n\n"
            f"🔗 [原文链接]({it['url']})\n"
        )

    digest = (
        f"# 🤖 AI/科技早报 | {today}\n\n"
        f"## 今日速览\n{top_one_liners}\n\n---\n\n"
        + "\n---\n".join(entries)
        + "\n\n> 📬 由 AI 自动生成并人工审核。如有错误请联系修正。\n"
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

    # Step 1: filter
    articles = filter_articles(articles)

    # Step 2: summarize each
    for i, a in enumerate(articles):
        print(f"[process] summarizing {i+1}/{len(articles)}: {a['title'][:50]}")
        articles[i] = summarize_article(a)

    # Step 3: multi-style posts for top articles
    posts_map = {}
    for i, a in enumerate(articles[:10]):
        if a.get("digest", {}).get("relevance_score", 0) > 0.6:
            print(f"[process] rewriting {i+1}: {a['digest'].get('title_cn', '')[:40]}")
            posts_map[a["id"]] = generate_social_posts(a)

    # Step 4: assemble digest
    digest = assemble_digest(articles, posts_map)
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
