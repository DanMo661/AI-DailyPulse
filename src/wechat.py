"""WeChat 公众号 publishing support (manual paste mode).

Converts the digest markdown into WeChat-editor-friendly HTML with inline
styles — the 公众号 editor strips CSS classes and <style> tags, so every
element carries its styling inline. The pipeline writes
output/wechat/YYYYMMDD_公众号.html; the human opens it in a browser,
select-all + copy, and pastes into the 公众号 editor — formatting survives
the paste.

API auto-publish (草稿箱/发布接口) is deliberately NOT implemented yet: it
needs a registered 公众号 (appid/secret) AND a fixed egress IP for 微信's
IP whitelist, which GitHub Actions runners can't provide. Revisit once the
account exists and the manual loop has proven the content works (4 weeks).
"""

import re
from datetime import datetime

from config import BEIJING_TZ, LINK_PREFIX, OUTPUT_DIR

_FONT = ("font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
         "'Microsoft YaHei',sans-serif;")

_LINK_STYLE = "color:#1a73e8;text-decoration:none;"


def _inline(md: str) -> str:
    """Convert inline markdown (bold / links / code) to styled HTML."""
    s = md
    s = re.sub(r"\*\*(.+?)\*\*",
               r'<strong style="color:#1a1a1a;">\1</strong>', s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)",
               rf'<a href="\2" style="{_LINK_STYLE}">\1</a>', s)
    s = re.sub(r"`(.+?)`",
               r'<code style="background:#f1f3f5;padding:1px 4px;'
               r'border-radius:3px;font-size:13px;">\1</code>', s)
    return s


def _link_paragraph(url: str) -> str:
    """The standalone 原文链接 line of the v3 digest, as a clickable link."""
    return (
        f'<p style="margin:8px 0 2px;font-size:13px;">'
        f'<a href="{url}" style="{_LINK_STYLE}">原文链接</a></p>'
    )


def digest_to_wechat_html(digest: str) -> tuple[str, str]:
    """Convert a v3 digest (headline + two-paragraph picks) into
    (title, wechat_html).

    Handles exactly the shape produced by process.assemble_digest:
    H1 date title, 🔥 headline section (H3 + paragraph + cover +
    原文链接 line), 📌 picks where each item is a `N. **title**` line,
    its own blurb paragraph and its own 原文链接 line.
    """
    title = f"AI DailyPulse | {datetime.now(BEIJING_TZ).strftime('%Y年%m月%d日')}"
    parts = [
        f'<section style="{_FONT}font-size:15px;color:#333;'
        f'line-height:1.8;letter-spacing:0.3px;padding:0 4px;">'
    ]
    pick_buf = []         # finished pick cards, wrapped in one grey list box
    pending = None        # {'num', 'title', 'blurb'} — pick awaiting its link line

    def flush_pending():
        nonlocal pending
        if pending:
            # link line never arrived — still render what we have
            card = (
                f'<div style="padding:10px 0;border-bottom:1px solid #ececec;">'
                f'<p style="margin:0 0 4px;font-weight:600;color:#1a1a1a;'
                f'line-height:1.6;">{pending["num"]}. {_inline(pending["title"])}</p>'
                f'<p style="margin:0;font-size:13.5px;color:#666;'
                f'line-height:1.7;">{_inline(pending.get("blurb", ""))}</p></div>'
            )
            pick_buf.append(card)
            pending = None

    def flush_picks():
        nonlocal pending
        flush_pending()
        if pick_buf:
            parts.append(
                '<div style="background:#f7f8fa;border-radius:10px;'
                'padding:4px 14px;margin:14px 0;">'
                + "".join(pick_buf) + "</div>"
            )
            pick_buf.clear()

    for raw in digest.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):                      # H1 = article title
            title = line[2:].strip()
        elif line.startswith("## "):                   # section header
            flush_picks()
            section = line[3:].strip()
            parts.append(
                f'<h2 style="font-size:17px;font-weight:700;color:#1a1a1a;'
                f'margin:26px 0 12px;padding-left:10px;'
                f'border-left:4px solid #1a73e8;line-height:1.4;">'
                f"{section}</h2>"
            )
        elif line.startswith("### "):                  # headline title
            flush_picks()
            parts.append(
                f'<p style="font-size:18px;font-weight:700;color:#1a1a1a;'
                f'line-height:1.5;margin:14px 0 10px;">{_inline(line[4:].strip())}</p>'
            )
        elif line.startswith("!["):                    # cover image
            m = re.match(r"!\[.*?\]\((.+?)\)", line)
            if m:
                parts.append(
                    f'<img src="{m.group(1)}" alt="" '
                    f'style="width:100%;border-radius:8px;margin:10px 0;" />'
                )
        elif line.startswith(LINK_PREFIX):             # standalone link line
            url = line[len(LINK_PREFIX):].strip()
            if pending:                                # finishes a pick card
                num, t, blurb = pending["num"], pending["title"], pending.get("blurb", "")
                pick_buf.append(
                    f'<div style="padding:10px 0;'
                    f'border-bottom:1px solid #ececec;">'
                    f'<p style="margin:0 0 4px;font-weight:600;color:#1a1a1a;'
                    f'line-height:1.6;">{num}. '
                    f'<a href="{url}" style="{_LINK_STYLE}">{_inline(t)}</a></p>'
                    f'<p style="margin:0;font-size:13.5px;color:#666;'
                    f'line-height:1.7;">{_inline(blurb)}</p>'
                    f'<p style="margin:6px 0 0;font-size:13px;">'
                    f'<a href="{url}" style="{_LINK_STYLE}">原文链接</a></p></div>'
                )
                pending = None
            else:                                      # headline's link
                parts.append(_link_paragraph(url))
        elif re.match(r"^\d+\.\s", line):              # pick title line
            # NB: not flush_picks() — all picks of a section share one grey box;
            # only a stale pick (missing link line) gets flushed out here
            flush_pending()
            m = re.match(r"^(\d+)\.\s\*\*(.+?)\*\*$", line)
            if m:
                pending = {"num": m.group(1), "title": m.group(2), "blurb": ""}
            else:
                parts.append(f'<p style="margin:8px 0;">{_inline(line)}</p>')
        else:                                          # plain paragraph
            if pending and not pending["blurb"]:       # the pick's blurb paragraph
                pending["blurb"] = line
            else:
                flush_pending()
                parts.append(
                    f'<p style="margin:10px 0;line-height:1.8;">{_inline(line)}</p>'
                )
    flush_picks()
    parts.append("</section>")
    return title, "".join(parts)


def save_wechat_html(digest: str) -> str:
    """Write the paste-ready HTML for today's digest; return the path."""
    out_dir = OUTPUT_DIR / "wechat"
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    title, html = digest_to_wechat_html(digest)
    path = out_dir / f"{today}_公众号.html"
    path.write_text(
        "<!-- 用法：浏览器打开本文件 → Ctrl+A 全选 → Ctrl+C 复制 → "
        "粘贴到 公众号后台图文编辑器 → 填标题（见下方注释）→ 群发 -->\n"
        f"<!-- 标题：{title} -->\n"
        + html,
        encoding="utf-8",
    )
    print(f"[publish] wechat paste-ready html: {path}")
    return str(path)
