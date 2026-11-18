# 黑客松日报 · 扩搜索范围 + 界面 + 邮件排版 实施计划

> 日期：2026-11-18 · 状态：待实施
> 本文件是**自包含**的执行计划：新会话 / 新窗口只读本文档即可开工，无需重新调研。
> 关联设计文档：[specs/2026-07-24-hackathon-daily-design.md](../specs/2026-07-24-hackathon-daily-design.md)

---

## 0. 背景与已确认的决策

当前管道：GitHub Actions cron → LLM 联网搜索（GLM-4-search，OpenAI 兼容兜底）→ SQLite 标题去重 → Jinja2 渲染 → Resend 发信 → db commit 回仓库。

**本次已与需求方确认的三个方向：**

| # | 方向 | 已选方案 |
| --- | --- | --- |
| 1 | 界面 | **GitHub Pages 静态站**（每次 run 产出 `site/index.html` + `site/data.json`，无服务器） |
| 2 | 搜索范围 | **结构化源 Devpost / MLH / clist** + **免费 SERP（Serper 2,500 次、Tavily 1,000 次）** + **扇出多查询（按标签并发搜 LLM）** |
| 3 | 邮件排版 | **卡片化 + 按报名截止倒计时排序** + **空日也发「今日无新增」维持订阅感** |

**暂不做**（后续批次，见 §6）：国内结构化源（掘金活动/活动行/天池）、地域扩展（海外全球赛）、二次提醒、`.ics` 附件、打开率追踪。

---

## 1. 现状速览（执行前必读）

### 1.1 流水线（`src/main.py`，六步顺序）

```
预检环境变量 → build_provider_chain() → chain.search(today)
→ get_unseen()（纯查询） → render_email() → ResendMailer.send()
→ mark_pushed()（仅发送成功后）  [回写由 workflow 完成]
```

### 1.2 文件职责

| 文件 | 职责 |
| --- | --- |
| `src/main.py` | 编排，返回码 0/1 决定 job 红绿 |
| `src/store.py` | SQLite 去重。`get_unseen()` **只读**，`mark_pushed()` 才写（at-least-once 的核心） |
| `src/providers/base.py` | `LLMProvider` 抽象（`name` / `search(today)` / `from_env()`） |
| `src/providers/chain.py` | `ProviderChain` **顺序兜底**（首个成功即返回）+ `build_provider_chain()` 注册表 |
| `src/providers/_common.py` | `SYSTEM_PROMPT`、`parse_hackathons()`、`call_chat_api()`（4xx 不重试 / 5xx 退避） |
| `src/providers/glm.py` | 智谱 web_search；JSON 失败带 `JSON_HINT` 重试一次 |
| `src/providers/openai_provider.py` | OpenAI 兼容兜底 |
| `src/email_renderer.py` | Jinja2 + `safe_url` 过滤器，返回 `(subject, html)` |
| `src/mailer.py` | `ResendMailer`，4xx 立即失败 / 5xx 退避 1s,4s |
| `src/models.py` | `Hackathon` dataclass，`registration_url` 必填 |
| `.github/workflows/daily.yml` | cron `15 22 * * *`、pytest 门、Secrets 注入、回写 `data/` |

### 1.3 硬约束

- **无常驻服务器**：所有产物必须能落进 git 或 Pages。
- **runner 一次性**：状态只能靠 `data/hackathons.db` 回写。
- **仓库为 Public**：任何进 `site/data.json` 的内容都是公开的（邮箱等隐私**绝不能**进库）。
- **测试是发信前的门**：`pytest -v` 挂则 job 挂，每批次必须带测试。

---

## 2. 两处语义改动（先评审再动手）

这两处不是"加功能"，是**改既有语义**，做错会造成重复推送或召回不增反降。

### 2.1 Provider 链：从「兜底」改为「并集合并」

**现状语义**（`chain.py`）：顺序尝试，首个成功即返回 → 后面的 provider 永远没机会跑。
**问题**：这只适合"同一种数据的两个提供者互相兜底"，无法扩大召回。

**目标语义**（分层）：

```
顶层 FanIn（新增 providers/fanin.py）
  ├─ 并发执行下列所有源，取回各自结果
  ├─ 按 URL 归一化去重后合并为一份 list[Hackathon]
  ├─ 单源失败只记 warning，不影响其它源
  └─ 全部失败才抛 RuntimeError（含逐源错误摘要）
  │
  ├─ 结构化源: devpost / mlh / clist          （各自独立）
  ├─ 免费 SERP: serper / tavily               （各自独立）
  └─ LLM 搜索: FallbackChain（= 现 ProviderChain 语义）
                glm ──失败或返回空──> openai ──> 取第一个非空
```

**要点**：
- `ProviderChain` **保留**，改名为 `FallbackChain`（或保持原名在 LLM 内部复用），语义不变。
- 新增 `FanIn` 作为 `main.py` 唯一入口，接口仍是 `async def search(today: str) -> list[Hackathon]`。
- **`main.py` 无需改动**（`build_provider_chain()` 返回值换成人脸不变的 `FanIn` 即可）。
- LLM 内部链补一条：**返回空列表也算失败，继续 fallback**（现状空结果不触发 fallback，是本次要修的召回漏洞）。

### 2.2 去重身份：标题 hash → URL hash（带迁移）

**现状**：`title_hash TEXT UNIQUE`，标题归一化后 sha256 前 16 位。
**问题**：赛事改标题 = 重复推送；不同赛事标题撞车 = 漏推。**URL 才是稳定身份。**

**迁移方案（向后兼容，无一次性爆发）**：

```sql
-- init_db() 内, 幂等
ALTER TABLE hackathons ADD COLUMN url_hash TEXT;   -- 新增可空列
```

**查询规则**（`get_unseen()`）：

```python
# 命中即视为"已推送":
#   url_hash 命中
#   OR (该条 url_hash 为 NULL 且 title_hash 命中)   ← 兼容未迁移的老行
```

**写入规则**（`mark_pushed()`）：新行同时写 `title_hash` 与 `url_hash`；冲突键改为 **`url_hash` 优先**（`ON CONFLICT(url_hash)`，需要一个 `UNIQUE` 索引，用 `CREATE UNIQUE INDEX IF NOT EXISTS … ON hackathons(url_hash) WHERE url_hash IS NOT NULL` 的部分唯一索引；或退化为先查后写的两步，**测试覆盖即可，不必强求纯 SQL UPSERT**）。

**URL 归一化 `normalize_url()` 必做**：
1. strip 空白；小写 scheme/host；
2. 去 `utm_*` / `ref` / `from` / `spm` 等 tracking 参数；
3. 去末尾 `/`（`/` 与无 `/` 视为同一条）；
4. 只保留 `http/https`，其余（空、非字符串）→ 归为 `None`（退回 title_hash 路径）。

> ⚠️ **禁止**直接改 UNIQUE 约束重建表：老行会瞬间全部变成"新的"，次日重复推送一波。

---

## 3. 批次 0 · P0 隐患修复（先做）

| # | 文件 | 改动 | 验收 |
| --- | --- | --- | --- |
| 0.1 | `.github/workflows/daily.yml` | 顶层加 `concurrency: { group: hackathon-daily, cancel-in-progress: false }` | YAML 合法；两次手动触发不会并行 |
| 0.2 | `src/main.py` | ✅ 已完成：预检支持 `LLM_API_KEY` / `GLM_API_KEY` / `OPENAI_API_KEY` 任一；`RESEND/MAIL_FROM/MAIL_TO` 仍硬必填 | 已增加仅 `OPENAI_API_KEY` 配置通过预检的测试 |
| 0.3 | `src/store.py` | 实施 §2.2：`url_hash` 列 + `normalize_url()` + 查询兼容 + 写入规则 | 老记录仍判为已推送；同 URL 不同标题不重推 |
| 0.4 | `tests/test_store.py` | 补用例（见下） | `pytest -v` 全绿 |

**0.4 必补用例**：
- 老库（只有 `title_hash` 数据）读写不炸、老条目仍被去重；
- 同一 URL 不同标题 → 只推一次；
- URL 带 `utm_source` / 大小写 / 尾斜杠差异 → 判为同一条；
- `registration_url` 为空/非法 scheme → 回退 title_hash 路径；
- `get_unseen()` 仍然**不写库**（发送失败重试语义不被破坏）。

---

## 4. 批次 1 · 扩搜索范围（核心）

### 4.1 抽象层

- `base.py`：把 `LLMProvider` 泛化为 `SearchProvider`（`name` / `async search(today)` / 类方法 `from_env() -> Self | None`）。**保持 `from_env()` 返回 `None` 表示"未配置，链上跳过"的既有约定。**
- 旧名 `LLMProvider` 保留为别名，避免一次性改所有引用。

### 4.2 新增 provider（每个文件独立、可单独跳过）

| 文件 | 源 | 免费额度 | 备注 / 风险 |
| --- | --- | --- | --- |
| `providers/devpost.py` | Devpost | 不限 | **endpoint 需先探**：`devpost.com/hackathons` discover 页；若有可用 JSON/RSS 优先用。反爬或结构变化 → 记 warning 跳过，不阻塞其它源 |
| `providers/mlh.py` | MLH | 不限 | `api.mlhleague.io` 或赛事列表页解析 |
| `providers/clist.py` | clist.rocks | 不限 | 有官方 JSON API，需免费注册拿 `CLIST_USERNAME` / `CLIST_API_KEY`（进 Secrets）；未配置则跳过 |
| `providers/serper.py` | Serper | **2,500 次（免卡）** | `POST https://google.serper.dev/search`，header `X-API-KEY`，body `{q, num}`；**只做召回，结构化交给 LLM 抽取** |
| `providers/tavily.py` | Tavily | **1,000 credits/月** | `POST https://api.tavily.com/search`，`api_key` + `{query, max_results, search_depth}`；返回含正文，可直接抽取 |

> **endpoint 探测纪律**：每个源先写一个最小可达性验证（脚本或测试标记为 `@pytest.mark.skipif(no_key)`），确认返回结构后再写解析；拿不下来就跳过 + 日志说明，**不阻塞其它源**。

### 4.3 抽取共用件（`_common.py`）

新增 `extract_json(content: str) -> list[dict]`：
- 复用现有 `parse_hackathons` 的围栏剥离 + `json.loads` + 逐条 `Hackathon.from_dict` 容错；
- 供 **LLM 搜索、Serper 结果让 LLM 结构化、Tavily 结果让 LLM 结构化** 三处复用；
- SERP 类 provider 的流程：`搜索 API（拿链接+摘要）→ 一次便宜 LLM 调用（喂摘要 → 输出 Hackathon JSON）→ extract_json`。

### 4.4 扇出多查询（`glm.py` / LLM provider）

```python
QUERIES = [
    "AI / 大模型 / AIGC 类线上黑客松",
    "数据 / 机器学习 / 数据分析类",
    "全栈 / Web / 小程序类",
    "硬件 / 创客 / 物联网类（含线上赛道）",
    "面向在校学生的线上编程竞赛",
]
results = await asyncio.gather(*(self._search_one(q, today) for q in QUERIES))
# 合并 → 按 normalize_url 去重（交给顶层 FanIn 也行）
```
- 并发数受 LLM 免费额度约束：默认 4~5 个查询，可用 `LLM_FANOUT` 环境变量关闭（设为 `1` 即现状）。
- 单个查询失败记 warning，不影响其余。

### 4.5 组装（`chain.py` → `build_provider_chain()` 返回 `FanIn`）

```python
# 环境变量
SEARCH_SOURCES   # 逗号分隔, 默认 "devpost,mlh,clist,serper,tavily,glm"
LLM_PROVIDERS    # LLM 内部兜底链, 默认 "glm,openai"（语义不变, 补空结果 fallback）
```

默认推荐顺序 = **Devpost / MLH / clist（不限次）→ Serper → Tavily → GLM**（计费源排最后）。

### 4.6 密钥清单（新增）

| Secret | 必要性 | 说明 |
| --- | --- | --- |
| `SERPER_API_KEY` | 可选（推荐） | 免费 2,500 次 |
| `TAVILY_API_KEY` | 可选（推荐） | 免费 1,000 credits/月 |
| `CLIST_USERNAME` / `CLIST_API_KEY` | 可选 | 免费注册 |
| `LLM_FANOUT` | 可选 | 扇出查询数，默认 4 |

同步更新 `.env.example` 与 README 的 Secrets 表。
**全部可选**：一个 key 都不配时，管道退回现状（GLM 单源），测试仍全绿。

---

## 5. 批次 2 · 邮件排版

| # | 文件 | 改动 |
| --- | --- | --- |
| 5.1 | `src/models.py` | 加 `days_left: int | None`（`registration_deadline` 解析 `YYYY-MM-DD`，失败 = `None`）与 `urgency()` → `hot(≤3d) / soon(≤7d) / later / unknown`。**纯派生字段，不动 LLM 输出契约。** |
| 5.2 | `src/email_renderer.py` | 排序与分组**放在渲染层**（不污染数据层）：`days_left` 升序（`None` 排最后）→ 分组 `🔥 即将截止 (≤3 天)` / `📌 本周 (≤7 天)` / `📅 后续`；同时算统计条（今日新增 N · 即将截止 M · 本周累计 K）。 |
| 5.3 | `templates/daily_email.html.j2` | **重写为卡片式**：`max-width:600px` 居中、table 布局 + 内联样式（邮件客户端不支持外部 CSS）、每张卡片 = 标题 + 主办方 + 类型标签 chips + **倒计时徽章（红黄绿）** + 一句话简介 + `报名 / 详情` 双按钮、分组小节头、顶部统计条。**dark mode**：`<meta name="color-scheme" content="light dark">` + `@media (prefers-color-scheme: dark)`（配 `!important` 覆盖内联）。Outlook 用表格兜底，不依赖 flex。 |
| 5.4 | `src/email_renderer.py` | 签名改为 `render_email(...) -> tuple[str, str, str]`（+ **纯文本版** `text`），排序/分组逻辑两版共用，文本版用 `- ` 列表 + 截止日期前缀。 |
| 5.5 | `src/mailer.py` | payload 增加 `"text"`（Resend 原生支持，等价 multipart/alternative）。 |
| 5.6 | `src/main.py` + `templates/empty.html.j2` **新** | **空日也发**：`unseen` 为空时渲染「今日无新增」模板（含本周累计、即将截止 TOP3），`send` 后直接 `return 0`（**不调用 `mark_pushed`**，本来就是空集）。搜索彻底失败（`return 1` 路径）**仍然不发**——故障不伪装成日报。 |

**取舍记录**：空日发信会让"订阅感"稳定，代价是每天必发一封；若后续被判定为打扰，只需删 5.6 一个分支即可回退。

---

## 6. 批次 3 · GitHub Pages 界面

| # | 文件 | 改动 |
| --- | --- | --- |
| 6.1 | `src/site_export.py` **新** | 产出 `site/index.html` + `site/data.json`。数据来源 = 全量 `hackathons` 表（含 `first_seen_at` / `last_pushed_at` / `url_hash`，**不含任何邮箱**）。 |
| 6.2 | `site/index.html` **新** | 纯 vanilla JS 单文件（无构建）：读 `./data.json`；功能 = 搜索框（标题/主办方模糊）+ 类型标签 chips 筛选 + 来源筛选（可选）+ 按截止倒计时排序（红黄绿）+ 统计卡（累计 / 本周新增 / 近 7 天趋势）。移动端适配 + dark mode。 |
| 6.3 | `.github/workflows/daily.yml` | 新增 deploy job（依赖 `send`）：`actions/configure-pages` → `actions/upload-pages-artifact`（path: `site`）→ `actions/deploy-pages`；`permissions` 增加 `pages: write, id-token: write`。`send` job 中在回写步骤之后调用 `python -m src.site_export`。 |
| 6.4 | 一次性手动设置 | 仓库 **Settings → Pages → Source = "GitHub Actions"**（需需求方操作）。 |

> `site/data.json` 进 git 会制造 diff 噪音两个选择：**a)** 仅在 Pages artifact 里存在、不回写 main（推荐，deploy job 内生成）；**b)** 提交进 main 方便直接 raw 访问。默认 **a**。

---

## 7. 批次 4 · 后续（本次不做，留档）

- 二次提醒（距截止 3 天再推一次，需表结构加 `kind` + TTL 查询）
- 报名截止 `.ics` 附件（Resend 支持附件）
- 逐地址发信（当前多收件人单 POST，一个地址 422 会连坐全部）
- `git push` 失败重试（当前 push 失败 = 邮件已发但标记未回写 → 次日重推）
- 地域扩展（海外线上赛 scope 开关）
- Resend 打开率 / 点击率追踪
- `git push` 前的 `ruff` lint 门

---

## 8. 执行顺序与验收

```
批次 0（隐患，半天）→ 批次 1（搜索，1~2 天）→ 批次 2（邮件，1 天）→ 批次 3（界面，1 天）
   每批次 = 一次独立 commit / PR，带测试，随时可停可回滚
```

**全局验收清单**：
- [ ] `pytest -v` 全绿（每批次结束时）
- [ ] 无任何 key 配置时，管道行为 = 现状（GLM 单源），不炸
- [ ] `get_unseen()` 保持纯查询（发送失败次日重推的语义未被破坏）
- [ ] 老 `hackathons.db` 读写兼容，升级后**不会**爆发重复推送
- [ ] workflow 有 `concurrency`，且新增 Pages 权限不越权（`contents: write` 之外按 job 最小授权）
- [ ] `site/data.json` 不含邮箱、API key 等任何敏感信息
- [ ] README / `.env.example` 的 Secrets 表与实现同步

**风险与回滚**：每个批次独立 commit；`daily.yml` 可通过删 deploy job 秒级下线 Pages；新 provider 通过 `SEARCH_SOURCES` 环境变量逐个摘除，无需改代码。
