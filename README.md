# Hackathon Daily

每日 08:00（北京时间）自动推送国内线上黑客松信息到邮箱。

## 工作流程

1. GitHub Actions 定时触发（cron `15 22 * * *` = UTC 22:15，抵消 GitHub Actions 调度延迟后约北京 08:00 送达）
2. 并发搜索多个源（Devpost / MLH / clist / Serper / Tavily / GLM 扇出多查询），URL 归一化去重后合并；单源失败只记 warning，全失败才终止。LLM 内部仍按顺序兜底（GLM → OpenAI 兼容），空结果也触发 fallback
3. SQLite 去重：仅推送未见过的黑客松（URL 归一化后 hash 为主，标题 hash 兜底兼容老库）
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
| `LLM_API_KEY` | LLM Provider API Key（与 `GLM_API_KEY` 二选一；三选一即可开跑） | (你的 key) |
| `GLM_API_KEY` | 智谱 API Key（与 `LLM_API_KEY` 等价，可选） | (你的 key) |
| `LLM_BASE_URL` | LLM API 端点（可选） | `https://open.bigmodel.cn/api/paas/v4/` |
| `LLM_MODEL` | 模型名（可选） | `glm-4-search` |
| `LLM_PROVIDERS` | LLM 内部兜底链（可选，逗号分隔） | `glm,openai`（默认） |
| `LLM_FANOUT` | GLM 扇出查询条数（可选） | `4`；`1` = 单查询现状 |
| `SEARCH_SOURCES` | 顶层搜索源（可选，逗号分隔） | `devpost,mlh,clist,serper,tavily,glm`；设 `glm` = 仅 LLM 现状 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（可选；也可单独作为唯一 provider key） | (你的 key) |
| `OPENAI_BASE_URL` | OpenAI 兼容端点（可选） | `https://api.deepseek.com/v1` |
| `OPENAI_MODEL` | OpenAI 兼容模型名（可选） | `deepseek-chat` |
| `SERPER_API_KEY` | Serper API Key（可选，推荐；免费 2,500 次） | (你的 key) |
| `TAVILY_API_KEY` | Tavily API Key（可选，推荐；免费 1,000 credits/月） | (你的 key) |
| `CLIST_USERNAME` | clist.rocks 用户名（可选） | (你的用户名) |
| `CLIST_API_KEY` | clist.rocks API Key（可选） | (你的 key) |
| `RESEND_API_KEY` | Resend API Key | `re_xxx` |
| `MAIL_FROM` | 发件人地址 | `Hackathon Daily <onboarding@resend.dev>` |
| `MAIL_TO` | 收件人地址（逗号分隔多收件人） | `a@x.com,b@y.com` |

> `SERPER_API_KEY` / `TAVILY_API_KEY` / `CLIST_USERNAME` / `CLIST_API_KEY` / `LLM_FANOUT` / `SEARCH_SOURCES` 全部可选；一个都不配时退回原有 GLM 单源行为，不会报错。可用 `SEARCH_SOURCES` 逐个摘除新源而无需改代码。

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
