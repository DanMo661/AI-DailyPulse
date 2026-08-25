"""小红书半自动发布（本地运行，实验性）

小红书没有面向个人的官方发布 API，本脚本用 Playwright + 账号 cookie
模拟浏览器操作（非官方途径，存在平台风控风险，后果自负）。

用法:
    python scripts/publish_xiaohongshu.py                           # 用最新产物
    python scripts/publish_xiaohongshu.py --md output/digest.md --cover output/cover_20260825.jpg
    python scripts/publish_xiaohongshu.py --auto                     # 自动点"发布"（风险自负）

前置:
    1. pip install -r requirements-xhs.txt
    2. playwright install chromium
    3. .env 里配置 XHS_COOKIE=<登录后的 cookie 串>（浏览器登录小红书后，
       开发者工具 → Network → 复制任意 creator.xiaohongshu.com 请求的
       Cookie 请求头即可）
    4. 首次运行若弹出登录/滑块验证，手动扫码过一次后 cookie 会继续生效

行为: 默认停在"发布"按钮前，人工确认点击；--auto 直接点击发布。
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from config import env_str  # noqa: E402  (loads .env)

PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
DEFAULT_TAGS = "#AI #科技 #每日早报"


def parse_cookie(cookie_str: str):
    """'a1=xx; webId=yy' → playwright cookie list for .xiaohongshu.com."""
    cookies = []
    for kv in cookie_str.split(";"):
        kv = kv.strip()
        if "=" not in kv:
            continue
        name, value = kv.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".xiaohongshu.com",
            "path": "/",
        })
    return cookies


def extract_headline(md: str) -> tuple[str, str]:
    """Extract (title, body) from the digest's headline section."""
    m = re.search(r"### (.+?)\n\n(.+?)\n+\[原文链接\]", md, re.DOTALL)
    if not m:
        raise SystemExit("无法从 digest.md 解析头条标题/正文，请检查文件格式")
    title = m.group(1).strip()
    body = re.sub(r"!\[.*?\]\(.*?\)", "", m.group(2)).strip()  # drop cover markdown img
    return title, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--md", default=str(ROOT / "output" / "digest.md"))
    parser.add_argument("--cover", default="", help="封面图路径（自动找 output/cover_*）")
    parser.add_argument("--tags", default=DEFAULT_TAGS, help="末尾追加的标签，空格分隔")
    parser.add_argument("--auto", action="store_true", help="自动点击发布按钮")
    args = parser.parse_args()

    cookie = env_str("XHS_COOKIE")
    if not cookie:
        raise SystemExit("缺少 XHS_COOKIE 配置（见脚本头部说明）")

    md_path = Path(args.md)
    if not md_path.exists():
        raise SystemExit(f"找不到 {md_path}")
    title, body = extract_headline(md_path.read_text(encoding="utf-8"))

    cover = args.cover
    if not cover:
        covers = sorted((ROOT / "output").glob("cover_*"))
        if covers:
            cover = str(covers[-1])  # newest cover
    if not cover:
        print("警告: 未找到封面图，小红书要求至少 1 张图，请检查 output/cover_*")

    final_text = f"{body}\n\n{args.tags}"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        ctx.add_cookies(parse_cookie(cookie))
        page = ctx.new_page()
        page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if "登录" in page.title() or "creator.xiaohongshu.com/login" in page.url:
            print("cookie 失效，请重新登录导出 cookie 后重试")
            browser.close()
            sys.exit(1)

        # 封面/图片上传
        if cover:
            try:
                page.set_input_files('input[type="file"]', str(Path(cover).resolve()))
                page.wait_for_timeout(3000)
                print(f"已上传封面: {cover}")
            except Exception as e:
                print(f"封面上传失败（页面结构可能变化）: {e}")

        # 标题
        for sel in ['input[placeholder*="标题"]', 'input[name="title"]', "h1 input"]:
            try:
                page.fill(sel, title, timeout=3000)
                print(f"已填标题: {title}")
                break
            except Exception:
                continue

        # 正文（富文本编辑器）
        for sel in ['[contenteditable="true"]', ".ql-editor", "[data-placeholder] div"]:
            try:
                page.fill(sel, final_text, timeout=3000)
                print(f"已填正文（含标签 {args.tags}）")
                break
            except Exception:
                continue

        if args.auto:
            for sel in ['button:has-text("发布")', 'button:has-text("立即发布")']:
                try:
                    page.click(sel, timeout=5000)
                    print("已点击发布（自动模式）")
                    break
                except Exception:
                    continue
        else:
            print("内容已填好，默认模式：人工核验后点击“发布”（浏览器保持打开）")
            page.wait_for_timeout(120_000)
            browser.close()
            return

        page.wait_for_timeout(5000)
        browser.close()


if __name__ == "__main__":
    main()
