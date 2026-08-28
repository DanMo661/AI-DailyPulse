# AI DailyPulse

全自动 AI/科技早报管线：采集 → LLM 精选 → blog 式早报 + 封面图 → 多渠道发布。GitHub Actions 每天北京时间 08:00 / 20:00 定时运行。

## 流程（v2：精选重点 + 头条 Blog）

1. **采集** `src/collect.py` — 并行抓 HN / dev.to / ArXiv / RSS（hnrss、TechCrunch、Simon Willison、lobste.rs）约 30 篇，URL md5 去重，`data/seen_urls.json` 记录已见（CI 里靠 actions/cache 持久化，key 用 run_id 保证每次回写）
2. **单篇筛选+摘要** `src/process.py` — DeepSeek 每篇 1 次调用（JSON mode）：拒掉无关，留下相关篇目
3. **定稿** — 1 次"主编"调用：从候选挑 1 篇头条（抓重点的标题 + 120~180 字正文）+ 4 篇精选（中文标题 + 50 字简介 + 链接），其余丢弃
4. **封面图** `src/cover.py` — 抓头条原文网页的 `og:image`（官网官方分享图）存 `output/cover_YYYYMMDD.*`；抓不到不阻塞
5. **头条文案** — 头条 1 篇 × 5 平台（公众号/小红书/知乎/Telegram/抖音）
6. **组装** `output/digest.md` — blog 格式：`🔥 今日头条`（标题+正文+链接+封面引用）+ `📌 其他重点`（1.2.3.4 编号列表）
7. **发布** `src/publish.py` — 飞书机器人只推早报 1 条（整发）；WordPress 草稿；小红书/抖音文案不推飞书，只存 `output/`（manual_review/），随 CI artifact 上传

## 约定

- 配置全走环境变量（`.env` 本地 / repo secrets CI），空值自动回退默认——workflow 只传真实存在的 secret
- LLM 调用必须容错：单篇失败降级保留；**累计失败率 ≥50% 中止发布**（护栏）；封面图失败跳过
- 0 新文章是正常日（exit 0），不是失败
- 飞书签名算法特殊：HMAC key = `{timestamp}\n{secret}`，消息体为空，改 `_feishu_sign` 前先查官方文档
- 日期统一用北京时间（`config.BEIJING_TZ`）

## 密钥

- DeepSeek `DEEPSEEK_API_KEY`（命名 AIuse）：本地在项目根 `.env`（gitignored），GitHub 侧在 repo secret；两处已同步更新。密钥值不放本文件。
- 飞书 `FEISHU_WEBHOOK_URL` / `FEISHU_SECRET`：仅在 GitHub repo secret。
- `XHS_COOKIE`（小红书）：仅本地 `.env`，微调发布脚本用。

## 本地运行与验证

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt  # Git Bash
cp .env.example .env   # 填 DEEPSEEK_API_KEY（必填）
.venv/Scripts/python src/main.py --collect-only   # 验采集
.venv/Scripts/python src/main.py                  # 全流程
```

产物在 `output/`：`digest.md`、`cover_*.jpg`、`social_posts.json`、`manual_review/`。

## 小红书发布（本地、实验性）

平台无个人官方 API，用 Playwright + cookie 模拟编辑器（非官方途径，有风控风险）：

```bash
.venv/Scripts/pip install -r requirements-xhs.txt && playwright install chromium
# .env 里配 XHS_COOKIE（登录后从浏览器 Network 复制 Cookie 请求头）
.venv/Scripts/python scripts/publish_xiaohongshu.py            # 自动填内容，人工点发布
.venv/Scripts/python scripts/publish_xiaohongshu.py --auto     # 自动点发布（风险自负）
```

## CI

`.github/workflows/daily-digest.yml`。改动后用 `gh workflow run "AI DailyPulse"` 手动触发验证；schedule 长期不活跃会被 GitHub 自动禁用，用 `gh workflow enable` 恢复。artifact 含 `output/` 和 `data/raw_articles.json`（可下载后本地 `--process-only` 复现一期）。封面图会随每期自动提交到仓库 `covers/` 目录（保留最近 7 天），飞书消息里的图片链接即 `raw.githubusercontent.com/DanMo661/AI-DailyPulse/main/covers/...`。
