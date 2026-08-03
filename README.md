# Hackathon Daily

每日 08:00（北京时间）自动推送国内线上黑客松信息到邮箱。

## 工作流程

1. GitHub Actions 定时触发（cron `15 22 * * *` = UTC 22:15，抵消 GitHub Actions 调度延迟后约北京 08:00 送达）
2. 调用 LLM 联网搜索 API（默认 GLM-4-search，可配 OpenAI 兼容 fallback）获取当前可报名的线上黑客松
3. SQLite 去重：仅推送未见过的黑客松（标题归一化后 hash 去重）
4. 渲染 HTML 邮件
5. 通过 Resend API 发送到收件箱（支持多收件人）
6. 标记已推送，db 文件 commit 回写仓库实现跨次持久化

## 本地开发

### 1. 克隆仓库

```bash
git clone <repo-url>
cd hackathon-daily
```

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements-dev.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入真实 API key
```

### 4. 运行测试

```bash
pytest -v
```

### 5. 本地运行

```bash
python -m src.main
```

## 配置 GitHub Secrets

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Key | 说明 | 示例 |
|---|---|---|
| `LLM_API_KEY` | LLM Provider API Key | (你的 key) |
| `LLM_BASE_URL` | LLM API 端点（可选） | `https://open.bigmodel.cn/api/paas/v4/` |
| `LLM_MODEL` | 模型名（可选） | `glm-4-search` |
| `LLM_PROVIDERS` | Provider 列表（可选，逗号分隔） | `glm` 或 `glm,openai` |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（可选 fallback） | (你的 key) |
| `OPENAI_BASE_URL` | OpenAI 兼容端点（可选） | `https://api.deepseek.com/v1` |
| `OPENAI_MODEL` | OpenAI 兼容模型名（可选） | `deepseek-chat` |
| `RESEND_API_KEY` | Resend API Key | `re_xxx` |
| `MAIL_FROM` | 发件人地址 | `Hackathon Daily <onboarding@resend.dev>` |
| `MAIL_TO` | 收件人地址（逗号分隔多收件人） | `a@x.com,b@y.com` |

## 手动触发 workflow

GitHub 仓库 → Actions → Hackathon Daily → Run workflow

## 技术栈

- Python 3.11
- httpx（异步 HTTP 客户端）
- Jinja2（模板引擎）
- SQLite（去重持久化，标准库）
- Resend API（邮件发送）
- GitHub Actions（定时任务）

## 设计文档

详见 `docs/superpowers/specs/2026-07-24-hackathon-daily-design.md`
