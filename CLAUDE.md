# AI DailyPulse

全自动 AI/科技文摘管线：采集 → LLM 处理 → 多渠道发布。GitHub Actions 每天北京时间 08:00 / 20:00 定时运行。

## 架构

- `src/collect.py` — 并行抓取 HN / dev.to / ArXiv / RSS（hnrss、TechCrunch、Simon Willison、lobste.rs），按 URL md5 去重，`data/seen_urls.json` 记录已见（CI 里靠 actions/cache 持久化）
- `src/process.py` — DeepSeek 每篇一次调用完成筛选+中文摘要（JSON mode），前 5 篇生成多平台文案，最后拼 `output/digest.md` + `output/social_posts.json`
- `src/publish.py` — 飞书 webhook（带签名）/ Telegram / WordPress 草稿，另存本地文件供手动发公众号、小红书
- `src/main.py` — 编排，支持 `--collect-only / --process-only / --publish-only`

## 约定

- 配置全部走环境变量（`.env` 本地 / repo secrets CI），空值自动回退默认——workflow 只传真实存在的 secret
- LLM 调用必须容错：单篇失败跳过或降级，不允许炸整条管线
- 飞书签名算法特殊：HMAC key = `{timestamp}\n{secret}`，消息体为空，改 `_feishu_sign` 前先查官方文档
- 日期统一用北京时间（`config.BEIJING_TZ`）

## 本地运行与验证

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt  # Git Bash
cp .env.example .env   # 填 DEEPSEEK_API_KEY（必填）
.venv/Scripts/python src/main.py --collect-only   # 验采集
.venv/Scripts/python src/main.py                  # 全流程
```

产物在 `output/`：`digest.md`、`social_posts.json`、`manual_review/`。

## CI

`.github/workflows/daily-digest.yml`。改动后用 `gh workflow run "AI DailyPulse"` 手动触发验证；schedule 长期不活跃会被 GitHub 自动禁用，用 `gh workflow enable` 恢复。
