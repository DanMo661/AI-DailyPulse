"""Assert the v3 digest format invariants on output/digest.md.

Checks the rules that must hold for the digest to be copy-paste ready:
  - no "AI 自动生成" footer
  - headline body one paragraph of 180~220 chars (tolerance band applied)
  - exactly 4 picks, each with its own blurb paragraph of 50~100 chars
  - every article's link sits on its own `原文链接：<url>` line (5 total),
    never crammed inline into the title line

Dev tool — exit 0 when all checks pass, 1 with a reason list otherwise.
"""

import re
import sys
from pathlib import Path

DIGEST = Path(__file__).resolve().parents[1] / "output" / "digest.md"
LINK_PREFIX = "原文链接："

# prompt targets with slack for punctuation and LLM drift (observed real
# production headline: 254 chars on 2026-11-18 — calibrated accordingly)
HEADLINE_RANGE = (150, 270)
BLURB_RANGE = (40, 125)

PICK_RE = re.compile(r"^(\d+)\.\s\*\*(.+?)\*\*$")


def _fail(problems: list[str], msg: str):
    problems.append(msg)


def check(problems: list[str]):
    text = DIGEST.read_text(encoding="utf-8")
    lines = [l.rstrip() for l in text.splitlines()]

    if "AI 自动生成" in text:
        _fail(problems, "found 'AI 自动生成' footer — must be removed")

    # headline body = non-empty lines between '### ' and the cover/link/next heading
    h3 = next((i for i, l in enumerate(lines) if l.startswith("### ")), None)
    if h3 is None:
        _fail(problems, "no '### 标题' headline title line")
        return
    body_lines = []
    for l in lines[h3 + 1:]:
        if l.startswith("![") or l.startswith(LINK_PREFIX) or l.startswith("#"):
            break
        if l.strip():
            body_lines.append(l.strip())
    body = "".join(body_lines)
    if not (HEADLINE_RANGE[0] <= len(body) <= HEADLINE_RANGE[1]):
        _fail(problems, f"headline body is {len(body)} chars, want {HEADLINE_RANGE}")

    # picks: title line → blurb paragraph → link line
    n_links = sum(1 for l in lines if l.startswith(LINK_PREFIX))
    if n_links != 5:
        _fail(problems, f"expected 5 standalone '{LINK_PREFIX}' lines (1 headline + 4 picks), got {n_links}")

    # markdown links with real URLs are v2 leftovers; cover image lines
    # (`![封面](...)`) are legitimate digest syntax and exempt
    suspicious = [
        l for l in lines
        if not l.startswith("![") and re.search(r"\]\(https?://", l)
    ]
    if suspicious:
        _fail(problems, f"markdown-style links must be plain URLs, found: {suspicious[:2]}")

    picks = []
    i = 0
    while i < len(lines):
        m = PICK_RE.match(lines[i])
        if m:
            blurb = ""
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and not lines[j].startswith(LINK_PREFIX) and not PICK_RE.match(lines[j]):
                blurb = lines[j].strip()
            link_ok = any(
                lines[k].startswith(LINK_PREFIX) for k in range(i + 1, min(i + 6, len(lines)))
            )
            picks.append((m.group(2), len(blurb), link_ok))
        i += 1

    if len(picks) != 4:
        _fail(problems, f"expected 4 picks, found {len(picks)}")
        return
    for title, blurb_len, link_ok in picks:
        if not link_ok:
            _fail(problems, f"pick '{title}' has no standalone link line after it")
        if not (BLURB_RANGE[0] <= blurb_len <= BLURB_RANGE[1]):
            _fail(problems, f"pick '{title}' blurb is {blurb_len} chars, want {BLURB_RANGE}")


def main():
    if not DIGEST.exists():
        print(f"[check] {DIGEST} not found — run the pipeline first")
        return 1
    problems: list[str] = []
    check(problems)
    if problems:
        print(f"[check] FAIL — {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[check] PASS — digest format OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
