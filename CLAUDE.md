# AI DailyPulse

全自动 AI/科技早报管线：一天 4 批采集攒池 → 早上 LLM 精选定稿 → 飞书推送 + 归档。每天北京时间 **08:00 准时**出刊（cron-job.org 外部触发，GH cron 只做兜底）。

## 每日时间线（北京时间）

| 时间 | 动作 | workflow | 触发 |
|---|---|---|---|
| 14:00 / 20:00 / 02:00 | 采集批次 1-3：每源轮询选 10 篇入 `data/pool.json`，不推送、不耗 LLM | `collect.yml` | GH cron（延迟无妨） |
| 07:50 | 批次 4 采集 → 池内 ~40 篇 LLM 并行筛选（`LLM_FILTER_WORKERS` 默认 2，免费档 429 严；付费 key 可调高）→ 主编定稿 → 封面 → **推飞书** → 归档 | `daily-digest.yml` | **三班错峰** GH cron UTC 21:30/22:00/22:30 + runner 内 sleep 到 07:50（首班到达者执行，其余 guard 跳过） |
| 08:20 | 兜底：三班全没起来则立即补发；推完了则飞书送达标记（`data/feishu_sent.json` 随 cache 持久化）/归档分支 guard 直接跳过，绝不双推 | `daily-digest.yml` | GH cron `20 0 * * *` |

## 信息源（v3）

- **AIHOT**（aihot.news）主力源：官方公开 API `GET /api/v1/items?mode=selected&window=24h&limit=50`，匿名免 key，限流 60 req/min（每批只调 1 次）。条目字段：`title`（中文标题）/`summary`（中文 AI 导读）/`links.original`（原文链接）/`score`（0-100）/`publishedAt`/`category`。**无图片字段**，封面仍走原文 og:image。其摘要只当原料，仍过本管线 LLM 筛选改写。
- **中文**：量子位 `qbitai.com/feed`（已验证）。机器之心 RSS 已死（2026-11 实测返回 HTML）。
- **英文**：TechCrunch、Simon Willison、The Verge、Ars Technica、MIT Tech Review、lobste.rs、HN×2（Firebase API + hnrss，URL 去重）、dev.to、ArXiv cs.AI。
- 已弃用：Reddit（CI IP 被 403）、VentureBeat（feed 0 条）、X（官方 API $100/月起，免费通道全不稳）。
- 批次选取按**源轮询**（`collect._round_robin`）：每轮每源取 1 篇直到 `BATCH_SIZE=10`，防 HN 高分挤掉 score=0 的 RSS 新源。
- `feedparser` 走 urllib 无超时，`collect.py` 用 `socket.setdefaulttimeout(25)` 兜底（lobste.rs 本机不可达会无限挂起）。

## 格式规范（v3，直接复制粘贴版）

- 头条：标题 ≤25 字 + 正文 **180~220 字**自然段；其他重点 4 条：**标题行 / 简介 50~100 字（硬上限 110）/ `原文链接：<URL>` 独立一行**。
- 链接一律裸 URL（不写 markdown 链接），复制到任何平台可点；封面用 `![封面](cover_*.jpg)` 引用。
- **无 "AI 自动生成" 标注**（用户要求产出可直接复制发布）。
- 改格式必须同步三处：`process.assemble_digest`（生成）、`wechat.digest_to_wechat_html`（公众号 HTML 解析）、`scripts/check_format.py`（断言）。

## 状态与护栏

- `data/seen_urls.json`：已见 URL md5（保留 5000 条），跨运行去重；CI 靠 actions/cache 持久化（key 带 run_id 每次回写，restore-keys 前缀匹配）。
- `data/pool.json`：待发布池，上限 60 按 `fetched_at` 淘汰（`state.py`）。**飞书确认送达后才清池**；失败/中止保留给 08:20 兜底重试（批次 4 重复采集的内容被 seen 去重，池最多多攒一批）。
- 单篇 LLM 失败率 ≥50% → 当期中止（exit 1），池保留。0 新文章/池空是正常日（exit 0），不是失败。
- 飞书是**唯一必达渠道**：`main.py` 里飞书失败 → exit 1 → workflow 跳过归档 → 兜底重试。Telegram/WordPress 空值自动跳过。
- LLM 调用统一走 `llm.chat()`：2 次重试退避；改超时/重试只动这一处。

## 归档

`archive` 分支，每天 1 个 bot commit：`archive/YYYYMMDD.md` + `covers/cover_*.jpg`，不再 7 天清理（实测每天 ~150KB，封面 PNG 占大头）。**main 分支零 bot commit**（v2 时代的历史 bot commit 保留未改写；其 `covers/` 目录与无主脚本 check_artifact.py 已于 2026-11-18 移除）。飞书/公众号里的图链走 jsDelivr `@archive` 分支（`publish.COVERS_CDN_BASE`；raw.githubusercontent 国内不可靠）。归档步骤 `if: success()` + digest 文件存在性检查，只在飞书真送达后执行。

## 本地运行与验证

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt  # Git Bash
cp .env.example .env   # 填 LLM_API_KEY
.venv/Scripts/python src/main.py collect            # 采集一批入池（无需 key、不推送）
.venv/Scripts/python src/main.py publish --dry-run  # 消化池子产出全部产物，不真实推送、不清池
.venv/Scripts/python scripts/check_format.py        # 断言格式（头条字数/简介字数/链接独立成行/无 AI 标注）
.venv/Scripts/python src/main.py full               # 旧版一次性全流程（本地测试用）
```

产物在 `output/`：`digest.md`、`digest_YYYYMMDD.md`、`cover_*.jpg`、`social_posts.json`、`manual_review/`、`wechat/YYYYMMDD_公众号.html`。GitHub 直连本机不稳，git 远程操作用 `-c http.proxy=http://127.0.0.1:7897`。

## 密钥

- LLM key：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`（旧名 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 仍生效，workflow 两者都透传）。本地 `.env`；CI repo secrets。
- 飞书 `FEISHU_WEBHOOK_URL` / `FEISHU_SECRET`：唯一必达渠道，仅 repo secret。
- Telegram、WordPress：可选渠道，空值自动跳过。`XHS_COOKIE`（小红书）仅本地 `.env`。
- cron-job.org 的 GitHub PAT：细粒度、仅本仓库、Actions RW——**只在 cron-job.org 后台**，不进仓库。

## 定时触发（三班错峰 + runner 内等待，零外部服务）

- **主触发**：schedule UTC 21:30/22:00/22:30 三班错峰（北京 05:30/06:00/06:30）→ "Wait until 07:50 Beijing" 步 sleep 到 UTC 23:50 → 执行管线。**2026-11-19~22 实测 GH schedule 对本仓库系统性拥堵：单班连续 5 天整班丢失、兜底班迟到 1.5~3h**，故改三班冗余——一班落在窗口内即准点，等待步吸收 ≤2h 迟到；全迟到则首班立即执行（北京 ~08:00-09:00）。
- **兜底**：schedule `20 0 * * *`（北京 08:20），三班全没起来时补发。
- 已推完的班次由 guard（飞书送达标记 `data/feishu_sent.json` / 归档分支）直接跳过；`concurrency: group: daily-digest` 串行化所有触发，绝不并发双推。
- **绝对精确 8:00 的唯一路径是外部 dispatch**（cron-job.org 等，需注册账号）：`workflow_dispatch` 即时触发不等待，接入时把外部任务指向它即可，代码零改动。
- workflow schedule 长期不活跃（60 天无提交）会被 GitHub 自动禁用，`gh workflow enable "AI DailyPulse"` 恢复。

## 小红书发布（本地、实验性）

平台无个人官方 API，用 Playwright + cookie 模拟编辑器（非官方途径，有风控风险）：

```bash
.venv/Scripts/pip install -r requirements-xhs.txt && playwright install chromium
# .env 里配 XHS_COOKIE（登录后从浏览器 Network 复制 Cookie 请求头）
.venv/Scripts/python scripts/publish_xiaohongshu.py            # 自动填内容，人工点发布
.venv/Scripts/python scripts/publish_xiaohongshu.py --auto     # 自动点发布（风险自负）
```

## 公众号发布（手动粘贴模式，变现验证中）

每期早报自动生成公众号排版 HTML（`src/wechat.py`，全内联样式，编辑器直接吃），v3 格式：标题行、简介段、`原文链接` 可点击行分离。

```bash
# CI 每期自动产出 output/wechat/YYYYMMDD_公众号.html（随 artifact 上传）
# 人肉循环：下载 artifact → 浏览器打开 HTML → Ctrl+A/C → 粘贴到公众号后台 → 群发
```

- **阶段1（现在）**：手动粘贴验证内容（目标 4 周看阅读量/流量主）。
- **阶段2（账号就绪后）**：API 自动发布。**坑：公众平台有 IP 白名单，GitHub Actions 动态 IP 过不了**——需要家宽常驻机跑发布步骤（见仓库根 workspace 讨论记录）。另需先确认个人订阅号能否开通草稿箱 API（个人主体大概率不能认证），这是整个阶段 2 的前提。
- 密钥（阶段 2 才需要）：`WECHAT_APPID` / `WECHAT_SECRET`。

## CI

- `collect.yml`：UTC 06/12/18 触发，无 secret；artifact 含 `data/`（池快照，可本地 replay）。
- `daily-digest.yml`：`workflow_dispatch`（cron-job.org）+ 兜底 cron；guard 步骤读 archive 分支防双推；归档步骤见上。
- 手动验证：`gh workflow run collect.yml`、`gh workflow run "AI DailyPulse"`。
