# 黑客松每日推送 - 设计文档

**日期**: 2026-07-24
**状态**: 已通过设计评审，待编写实施计划
**作者**: 用户 + TRAE 协作

---

## 1. 背景与目标

用户希望每天早晨收到一封邮件，汇总当前中国大陆地区可报名/进行中的**线上黑客松**信息，避免错过报名截止时间。

**MVP 目标**：用最低成本验证「AI 联网搜索 + 邮件推送」这条链路是否能在每日早晨稳定产出可用的赛事列表。如果跑两周后发现覆盖不足，再针对性补充爬虫抓取特定站点。

## 2. 范围

### 2.1 In Scope

- 每日定时邮件推送（北京时间 08:00）
- AI 联网搜索国内线上黑客松
- 邮件包含：赛事基本信息、时间地点、报名链接
- 单用户使用（你自己）
- 部署在 GitHub Actions

### 2.2 Out of Scope（MVP 不做）

- 多用户订阅系统、认证、退订机制
- 数据持久化、去重逻辑（同一赛事可能连续多天出现，已确认接受）
- 爬虫抓取特定站点（后期补充）
- 奖金、参赛资格等字段抽取
- Web 界面、管理后台

### 2.3 事件类型范围

「线上黑客松」包括但不限于：

- 现场黑客松的线上版/线上赛道
- AI / 数据科学竞赛（如天池、DataFountain、和鲸社区等线上赛事）
- 大学生编程竞赛的线上赛道
- 创客马拉松的线上举办形式

不限定类型标签，凡是「线上、限时、有报名链接、当前可参与」即可。

## 3. 系统架构

```
┌─────────────────────────────────────────────┐
│  GitHub Actions                              │
│  (cron '0 0 * * *' = 北京 08:00)             │
│  + workflow_dispatch (手动触发)              │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │  main.py (单一入口)                   │  │
│  │                                       │  │
│  │  1. LLMSearchProvider.search()        │  │
│  │     → 返回 List[Hackathon]            │  │
│  │  2. email_renderer.render()           │  │
│  │     → HTML 字符串                     │  │
│  │  3. mailer.send(subject, html)        │  │
│  │     → 投递到收件箱                    │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  Secrets: LLM_API_KEY, LLM_BASE_URL,        │
│           RESEND_API_KEY, MAIL_TO,          │
│           MAIL_FROM                         │
└─────────────────────────────────────────────┘
                  ↓
        收件箱 15720214985@163.com
        (每日 08:00 左右)
```

**关键架构决策**：

- **单仓库 / 单脚本 / 单 workflow**——MVP 极简，便于迭代
- **无状态**：不写数据库、不维护 `seen.json`，每次邮件都是「当前快照」
- **Provider 抽象**：LLM 与邮件服务都抽象为接口，后续换 provider 不影响主流程
- **手动触发支持**：`workflow_dispatch` 用于调试和首次验证

## 4. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11 | AI/搜索/邮件生态成熟；后续补爬虫天然适配 |
| LLM Provider | 抽象接口 + GLM-4-search 默认实现 | 用户暂未定，设计成可插拔；GLM-4-search 国内直连、中文赛事覆盖好 |
| 邮件服务 | Resend API | 免费 3000 封/月足够；API 简洁；送达率优于 SMTP |
| 模板引擎 | Jinja2 | Python HTML 渲染事实标准 |
| 包管理 | `requirements.txt` | 简单稳定，GitHub Actions 友好 |
| 测试 | pytest | 标准 |
| Lint | ruff | 快、零配置 |

## 5. 数据结构

LLM 输出结构化 JSON，解析为以下 dataclass：

```python
from dataclasses import dataclass

@dataclass
class Hackathon:
    name: str                     # 赛事名称
    organizer: str                 # 主办方
    type_tag: str                  # 类型标签：AI/数据/全栈/创意/...
    summary: str                   # 一句话简介
    registration_deadline: str     # 报名截止（ISO 日期 "YYYY-MM-DD" 或 "待定"）
    start_date: str                # 比赛开始（ISO 日期 或 "待定"）
    end_date: str                  # 比赛结束（ISO 日期 或 "待定"）
    location: str                  # 固定为 "线上" 或含线上描述
    registration_url: str          # 报名链接（必填，缺失则丢弃此项）
    detail_url: str | None         # 官网/详情页（可选）
```

**字段约束**：
- `registration_url` 必填，缺失或无效的整条记录丢弃
- 日期字段允许「待定」字符串作为兜底
- `location` 主要为「线上」，但允许「线上 + 北京线下决赛」等组合描述

## 6. 项目结构

```
hackathon-daily/
├── .github/
│   └── workflows/
│       └── daily.yml              # cron + workflow_dispatch
├── src/
│   ├── __init__.py
│   ├── main.py                    # 入口：编排三步
│   ├── llm_search.py              # LLMSearchProvider 接口 + GLM 实现
│   ├── email_renderer.py          # Jinja2 渲染
│   ├── mailer.py                  # Resend provider
│   └── models.py                  # Hackathon dataclass
├── templates/
│   └── daily_email.html.j2        # 邮件模板
├── tests/
│   ├── __init__.py
│   ├── test_email_renderer.py     # 给定 fixture，断言 HTML
│   └── fixtures/
│       └── sample_hackathons.json
├── .env.example                   # 本地开发配置模板
├── requirements.txt
├── pyproject.toml                 # ruff 配置
└── README.md
```

## 7. 数据流（详细）

```
1. GitHub Actions cron 触发 workflow (UTC 00:00 → 北京 08:00)
2. workflow 拉起 Python 3.11 环境，安装依赖
3. main.py 启动
4. LLMSearchProvider.search() 执行
   a. 构造 prompt：
      - 注入今日日期（北京时间）
      - 限定：中国大陆、线上、当前可报名或进行中
      - 输出格式：严格 JSON 数组，schema 约束见第 5 节
      - 排除：已结束、报名已截止、纯线下赛事
   b. 调用 LLM 联网搜索 API
   c. 解析响应 → List[Hackathon]
   d. 字段校验：
      - registration_url 缺失 → 丢弃
      - 日期非法 → 替换为 "待定"
5. 若 List 为空 → 跳过发送，仅写日志，正常退出
6. email_renderer.render(hackathons, today)
   a. 加载 templates/daily_email.html.j2
   b. 渲染为 HTML 字符串
7. mailer.send(subject, html)
   a. subject 格式: "黑客松日报 - 2026-07-24（N 场可报名）"
   b. 调用 Resend API
   c. 成功 → 日志 "已发送至 15720214985@163.com"
8. workflow 退出码反映成功/失败
```

## 8. LLM Prompt 设计要点

**系统提示**要点：

- 角色：国内线上黑客松信息聚合助手
- 任务：搜索当前中国大陆地区**仍可报名或正在进行中**的线上黑客松/编程竞赛/创客马拉松
- 时间过滤：报名截止 ≥ 今天，或比赛尚未结束
- 地域过滤：中国大陆主办方或面向中国大陆参赛者
- 形式过滤：必须是线上或含线上赛道
- 输出：严格 JSON 数组，每个元素符合第 5 节 schema
- 拒绝返回：纯线下赛事、已结束赛事、报名已截止赛事、无法获取报名链接的赛事
- 输出语言：中文

**Few-shot**：在 prompt 中给 1-2 个期望输出示例，提高 JSON 一致性。

**容错**：要求 LLM 只返回 JSON，不包含 markdown 代码块标记或解释性文字。

## 9. 错误处理

| 场景 | 策略 | 影响 |
|---|---|---|
| LLM API 超时 / 5xx | retry 2 次，指数退避（1s, 4s）；仍失败 → workflow 报错退出 | 当日无邮件，GitHub 发告警邮件 |
| LLM 返回非 JSON / schema 不符 | retry 1 次，附加「请只返回合法 JSON 数组」提示；仍失败 → 跳过当次发送 | 当日无邮件，日志记录 |
| LLM 返回空列表 | **不发邮件**，仅写日志，正常退出 | 避免噪音邮件 |
| 单条 Hackathon 字段缺失 | `registration_url` 缺失 → 丢弃整条；其它字段缺失 → 用「未知」/「待定」填充 | 不阻塞整体 |
| 邮件 API 失败 | retry 2 次；失败 → workflow 失败 | GitHub 发告警邮件 |
| GitHub Actions cron 延迟 | 接受 5-30 分钟延迟，不处理 | 已知限制 |

## 10. 测试策略

### 10.1 自动化测试

- `test_email_renderer.py`：
  - 给定固定 `List[Hackathon]` fixture（含完整字段、含缺失字段两种 case）
  - 断言 HTML 输出包含：每条赛事的 name、registration_url、日期
  - 断言缺失字段被正确兜底为「待定」/「未知」

### 10.2 手动验证

- `workflow_dispatch` 手动触发 workflow，观察：
  - LLM 是否返回合法 JSON
  - 邮件是否送达 `15720214985@163.com`
  - HTML 渲染是否正常（不乱码、链接可点击）
- 不写 LLM 搜索的自动化测试（结果不稳定）

### 10.3 Mailer 测试

- 使用 mock，断言 Resend API 被正确调用（参数、收件人、主题）
- 不实际发邮件

## 11. 配置与密钥

### 11.1 GitHub Secrets

| Key | 用途 | 示例 |
|---|---|---|
| `LLM_API_KEY` | LLM Provider API Key | (待用户提供) |
| `LLM_BASE_URL` | LLM API 端点（便于切换 provider） | `https://open.bigmodel.cn/api/paas/v4/` |
| `LLM_MODEL` | 模型名 | `glm-4-search` |
| `RESEND_API_KEY` | Resend API Key | `re_xxx` |
| `MAIL_TO` | 收件人 | `15720214985@163.com` |
| `MAIL_FROM` | 发件人（需在 Resend 验证域名或用默认 onboarding 域） | `Hackathon Daily <onboarding@resend.dev>` |

### 11.2 本地开发

- `.env.example` 提供所有环境变量模板
- `.env`（gitignore）填本地真实值用于本地调试
- `python -m src.main` 直接运行

## 12. cron 配置

```yaml
on:
  schedule:
    - cron: '0 0 * * *'   # UTC 00:00 = 北京 08:00
  workflow_dispatch:        # 手动触发，调试用
```

**已知限制**：
- GitHub Actions cron 实际触发可能延迟 5-30 分钟（高峰时更长）
- 不保证精确到秒，对每日邮件场景可接受
- cron 触发的 workflow 没有手动参数，所有配置走 Secrets

## 13. 后续演进路径（非本期实施）

按优先级排序，仅记录思路，不在 MVP 实施：

1. **去重**：跑两周后若重复噪音明显，引入 `seen.json` 记录已推送 URL，只推送新增 + 临近截止的
2. **爬虫补充**：针对 AI 搜索漏报严重的站点（如天池、和鲸），写定向爬虫
3. **奖金/参赛资格字段**：根据实际需求决定是否扩展 schema
4. **多用户订阅**：若分享给朋友，引入订阅/退订机制
5. **Web 归档页**：GitHub Pages 渲染历史邮件
6. **Provider 扩展**：新增 Perplexity、Tavily+LLM 等 provider，对比效果

## 14. 验收标准

MVP 完成定义为：

1. ✅ GitHub Actions workflow 能在 UTC 00:00 自动触发
2. ✅ `workflow_dispatch` 能手动触发
3. ✅ LLM 调用成功，返回结构化 JSON 解析为 `List[Hackathon]`
4. ✅ 邮件成功送达 `15720214985@163.com`
5. ✅ 邮件 HTML 渲染正确：包含每条赛事的名称、类型、时间、报名链接
6. ✅ 缺失字段有兜底显示，不报错
7. ✅ 空结果时不发邮件，不报错
8. ✅ 单元测试 `test_email_renderer.py` 通过
9. ✅ README 说明如何配置 Secrets 和手动触发

---

**附注**：

- Resend 免费域名 `onboarding@resend.dev` 仅能发往注册邮箱，若要发到 `15720214985@163.com`，需在 Resend 验证自有域名或更换为已验证域名。这是部署阶段需要解决的细节，不影响代码结构。备选方案：改用 QQ 邮箱 SMTP（零成本，但送达率不稳定）。
