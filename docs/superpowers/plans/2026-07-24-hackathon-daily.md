# 黑客松每日推送 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个 GitHub Actions 定时任务，每日 08:00（北京时间）调用 LLM 联网搜索 API 抓取国内可报名的线上黑客松，渲染 HTML 邮件并通过 Resend API 发送到指定邮箱。

**Architecture:** 单仓库 / 单脚本 / 单 workflow。Python 3.11 实现，模块拆分为 `models` / `llm_search` / `email_renderer` / `mailer` / `main` 五个文件，每个文件单一职责。LLM 与邮件服务都抽象为接口，默认实现是 GLM-4-search 和 Resend。无状态、无数据库、不去重。

**Tech Stack:** Python 3.11、httpx（异步 HTTP）、Jinja2（模板）、Resend API（邮件）、GLM-4-search（LLM 联网搜索）、GitHub Actions（cron + workflow_dispatch）、pytest + pytest-asyncio（测试）、ruff（lint）。

---

## 文件结构总览

实施过程中将创建/修改以下文件：

| 文件 | 责任 | 创建任务 |
|---|---|---|
| `.gitignore` | 忽略 Python 缓存、虚拟环境、.env | Task 1 |
| `requirements.txt` | 运行时依赖 | Task 1 |
| `requirements-dev.txt` | 开发依赖（含运行时） | Task 1 |
| `pyproject.toml` | ruff / pytest 配置 | Task 1 |
| `.env.example` | 环境变量模板 | Task 1 |
| `src/__init__.py` | 包标识（空文件） | Task 1 |
| `tests/__init__.py` | 包标识（空文件） | Task 1 |
| `src/models.py` | `Hackathon` dataclass + `from_dict` | Task 2 |
| `tests/test_models.py` | 模型解析测试 | Task 2 |
| `tests/fixtures/sample_hackathons.json` | 渲染测试 fixture | Task 3 |
| `templates/daily_email.html.j2` | 邮件 HTML 模板 | Task 3 |
| `src/email_renderer.py` | `render_email(hackathons, today)` | Task 3 |
| `tests/test_email_renderer.py` | 渲染测试 | Task 3 |
| `src/mailer.py` | `ResendMailer.send(subject, html)` | Task 4 |
| `tests/test_mailer.py` | Mailer mock 测试 | Task 4 |
| `src/llm_search.py` | `GLMSearchProvider.search(today)` | Task 5 |
| `tests/test_llm_search.py` | LLM 搜索 mock 测试 | Task 5 |
| `src/main.py` | 编排入口（search → render → send） | Task 6 |
| `.github/workflows/daily.yml` | cron + workflow_dispatch | Task 7 |
| `README.md` | 配置与使用说明 | Task 8 |

---

## Task 1: 项目脚手架

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: 创建 .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.env

# IDE
.vscode/
.idea/

# Tests
.pytest_cache/
.coverage
htmlcov/

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 2: 创建 requirements.txt（运行时依赖）**

```text
httpx>=0.27.0
jinja2>=3.1.0
python-dotenv>=1.0.0
```

- [ ] **Step 3: 创建 requirements-dev.txt（开发依赖）**

```text
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
ruff>=0.5.0
```

- [ ] **Step 4: 创建 pyproject.toml**

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
```

- [ ] **Step 5: 创建 .env.example**

```text
LLM_API_KEY=
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4-search
RESEND_API_KEY=
MAIL_FROM=Hackathon Daily <onboarding@resend.dev>
MAIL_TO=15720214985@163.com
```

- [ ] **Step 6: 创建空 __init__.py 与 fixtures 目录占位**

`src/__init__.py`：
```python
```

`tests/__init__.py`：
```python
```

`tests/fixtures/.gitkeep`：
```text
```

- [ ] **Step 7: git init 并首次提交**

```bash
cd "c:\Users\lenovo\Desktop\黑客松"
git init
git add .gitignore requirements.txt requirements-dev.txt pyproject.toml .env.example src/__init__.py tests/__init__.py tests/fixtures/.gitkeep docs/
git commit -m "chore: scaffold project structure"
```

预期输出：`[main (root-commit) ...] chore: scaffold project structure`

---

## Task 2: Hackathon 数据模型（TDD）

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 写失败的测试 tests/test_models.py**

```python
import pytest

from src.models import Hackathon


def test_from_dict_complete():
    data = {
        "name": "测试黑客松",
        "organizer": "测试方",
        "type_tag": "AI",
        "summary": "测试简介",
        "registration_deadline": "2026-08-01",
        "start_date": "2026-08-15",
        "end_date": "2026-08-17",
        "location": "线上",
        "registration_url": "https://example.com/register",
        "detail_url": "https://example.com",
    }
    h = Hackathon.from_dict(data)
    assert h.name == "测试黑客松"
    assert h.organizer == "测试方"
    assert h.type_tag == "AI"
    assert h.registration_url == "https://example.com/register"
    assert h.detail_url == "https://example.com"


def test_from_dict_missing_registration_url_raises():
    data = {"name": "测试", "organizer": "方"}
    with pytest.raises(ValueError, match="registration_url is required"):
        Hackathon.from_dict(data)


def test_from_dict_missing_fields_use_defaults():
    data = {"registration_url": "https://example.com"}
    h = Hackathon.from_dict(data)
    assert h.name == "未知"
    assert h.organizer == "未知"
    assert h.type_tag == "未知"
    assert h.summary == ""
    assert h.registration_deadline == "待定"
    assert h.start_date == "待定"
    assert h.end_date == "待定"
    assert h.location == "线上"
    assert h.detail_url is None


def test_from_dict_empty_registration_url_raises():
    data = {"name": "测试", "registration_url": ""}
    with pytest.raises(ValueError, match="registration_url is required"):
        Hackathon.from_dict(data)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd "c:\Users\lenovo\Desktop\黑客松"
pip install -r requirements-dev.txt
pytest tests/test_models.py -v
```

预期：`ModuleNotFoundError: No module named 'src.models'` 或类似导入错误。

- [ ] **Step 3: 实现 src/models.py**

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class Hackathon:
    """黑客松数据模型。"""

    name: str
    organizer: str
    type_tag: str
    summary: str
    registration_deadline: str
    start_date: str
    end_date: str
    location: str
    registration_url: str
    detail_url: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hackathon":
        """从字典构造 Hackathon。registration_url 必填，缺失抛 ValueError。"""
        url = data.get("registration_url")
        if not url:
            raise ValueError("registration_url is required")
        return cls(
            name=data.get("name") or "未知",
            organizer=data.get("organizer") or "未知",
            type_tag=data.get("type_tag") or "未知",
            summary=data.get("summary") or "",
            registration_deadline=data.get("registration_deadline") or "待定",
            start_date=data.get("start_date") or "待定",
            end_date=data.get("end_date") or "待定",
            location=data.get("location") or "线上",
            registration_url=url,
            detail_url=data.get("detail_url"),
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_models.py -v
```

预期：4 个测试全部 PASSED。

- [ ] **Step 5: 提交**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(models): add Hackathon dataclass with from_dict validation"
```

---

## Task 3: 邮件渲染器（TDD）

**Files:**
- Create: `tests/fixtures/sample_hackathons.json`
- Create: `templates/daily_email.html.j2`
- Create: `src/email_renderer.py`
- Create: `tests/test_email_renderer.py`

- [ ] **Step 1: 写测试 fixture tests/fixtures/sample_hackathons.json**

```json
[
  {
    "name": "示例AI黑客松",
    "organizer": "示例主办方",
    "type_tag": "AI",
    "summary": "面向AI开发者的线上马拉松",
    "registration_deadline": "2026-08-01",
    "start_date": "2026-08-15",
    "end_date": "2026-08-17",
    "location": "线上",
    "registration_url": "https://example.com/register",
    "detail_url": "https://example.com"
  },
  {
    "name": "极简赛事",
    "organizer": "未知",
    "type_tag": "未知",
    "summary": "",
    "registration_deadline": "待定",
    "start_date": "待定",
    "end_date": "待定",
    "location": "线上",
    "registration_url": "https://example.com/minimal",
    "detail_url": null
  }
]
```

- [ ] **Step 2: 写失败的测试 tests/test_email_renderer.py**

```python
import json
from pathlib import Path

from src.email_renderer import render_email
from src.models import Hackathon

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture() -> list[Hackathon]:
    data = json.loads((FIXTURES / "sample_hackathons.json").read_text(encoding="utf-8"))
    return [Hackathon.from_dict(item) for item in data]


def test_render_email_contains_name_and_url():
    hackathons = _load_fixture()
    subject, html = render_email(hackathons, "2026-07-24")
    assert "示例AI黑客松" in html
    assert "https://example.com/register" in html
    assert "极简赛事" in html
    assert "https://example.com/minimal" in html


def test_render_email_subject_format():
    hackathons = _load_fixture()
    subject, _ = render_email(hackathons, "2026-07-24")
    assert subject == "黑客松日报 - 2026-07-24（2 场可报名）"


def test_render_email_displays_dates():
    hackathons = _load_fixture()
    _, html = render_email(hackathons, "2026-07-24")
    assert "2026-08-01" in html
    assert "2026-08-15" in html
    assert "2026-08-17" in html


def test_render_email_handles_missing_fields():
    hackathons = _load_fixture()
    _, html = render_email(hackathons, "2026-07-24")
    # 缺失字段应渲染为「待定」/「未知」
    assert "待定" in html
    assert "未知" in html


def test_render_email_displays_today():
    hackathons = _load_fixture()
    _, html = render_email(hackathons, "2026-07-24")
    assert "2026-07-24" in html
```

- [ ] **Step 3: 运行测试验证失败**

```bash
pytest tests/test_email_renderer.py -v
```

预期：`ModuleNotFoundError: No module named 'src.email_renderer'`。

- [ ] **Step 4: 实现 src/email_renderer.py**

```python
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Hackathon

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def render_email(hackathons: list[Hackathon], today: str) -> tuple[str, str]:
    """渲染邮件，返回 (subject, html)。"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("daily_email.html.j2")
    html = template.render(hackathons=hackathons, today=today, count=len(hackathons))
    subject = f"黑客松日报 - {today}（{len(hackathons)} 场可报名）"
    return subject, html
```

- [ ] **Step 5: 实现 templates/daily_email.html.j2**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>黑客松日报 - {{ today }}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif; max-width: 640px; margin: 0 auto; padding: 20px; color: #333;">
  <h1 style="color: #1a1a1a; border-bottom: 2px solid #4f46e5; padding-bottom: 10px;">
    黑客松日报
  </h1>
  <p style="color: #666; font-size: 14px;">{{ today }} · 共 {{ count }} 场可报名</p>

  {% if not hackathons %}
  <p>今日暂无可报名的线上黑客松。</p>
  {% endif %}

  {% for h in hackathons %}
  <div style="margin-bottom: 24px; padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px;">
    <h2 style="margin: 0 0 8px 0; color: #1a1a1a; font-size: 18px;">
      {{ h.name }}
      <span style="display: inline-block; padding: 2px 8px; background: #eef2ff; color: #4f46e5; border-radius: 4px; font-size: 12px; margin-left: 8px;">{{ h.type_tag }}</span>
    </h2>
    <p style="margin: 4px 0; color: #666; font-size: 14px;">主办方：{{ h.organizer }}</p>
    {% if h.summary %}<p style="margin: 8px 0; color: #333; font-size: 14px;">{{ h.summary }}</p>{% endif %}
    <table style="width: 100%; font-size: 14px; margin: 8px 0;">
      <tr><td style="color: #999; padding: 2px 0; width: 100px;">报名截止</td><td>{{ h.registration_deadline }}</td></tr>
      <tr><td style="color: #999; padding: 2px 0;">比赛时间</td><td>{{ h.start_date }} ~ {{ h.end_date }}</td></tr>
      <tr><td style="color: #999; padding: 2px 0;">地点</td><td>{{ h.location }}</td></tr>
    </table>
    <p style="margin: 12px 0 0 0;">
      <a href="{{ h.registration_url }}" style="display: inline-block; padding: 8px 16px; background: #4f46e5; color: #fff; text-decoration: none; border-radius: 4px; font-size: 14px;">立即报名</a>
      {% if h.detail_url %}<a href="{{ h.detail_url }}" style="display: inline-block; padding: 8px 16px; color: #4f46e5; text-decoration: none; font-size: 14px; margin-left: 8px;">详情</a>{% endif %}
    </p>
  </div>
  {% endfor %}

  <hr style="margin-top: 32px; border: none; border-top: 1px solid #e5e7eb;">
  <p style="color: #999; font-size: 12px;">本邮件由 Hackathon Daily 自动推送</p>
</body>
</html>
```

- [ ] **Step 6: 运行测试验证通过**

```bash
pytest tests/test_email_renderer.py -v
```

预期：5 个测试全部 PASSED。

- [ ] **Step 7: 提交**

```bash
git add src/email_renderer.py templates/daily_email.html.j2 tests/test_email_renderer.py tests/fixtures/sample_hackathons.json
git commit -m "feat(renderer): add Jinja2 email renderer with HTML template"
```

---

## Task 4: 邮件发送器（TDD）

**Files:**
- Create: `src/mailer.py`
- Create: `tests/test_mailer.py`

- [ ] **Step 1: 写失败的测试 tests/test_mailer.py**

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mailer import ResendMailer


@pytest.mark.asyncio
async def test_resend_send_calls_api_correctly():
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "email-123"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        mailer = ResendMailer(
            api_key="re_test",
            from_email="from@test.com",
            to_email="to@test.com",
        )
        await mailer.send("测试主题", "<html/>")

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args.kwargs
    assert call_kwargs["json"]["from"] == "from@test.com"
    assert call_kwargs["json"]["to"] == ["to@test.com"]
    assert call_kwargs["json"]["subject"] == "测试主题"
    assert call_kwargs["json"]["html"] == "<html/>"
    assert call_kwargs["headers"]["Authorization"] == "Bearer re_test"


@pytest.mark.asyncio
async def test_resend_send_retries_on_failure():
    mock_response_fail = MagicMock()
    mock_response_fail.raise_for_status.side_effect = Exception("500 error")
    mock_response_ok = MagicMock()
    mock_response_ok.json.return_value = {"id": "email-456"}
    mock_response_ok.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_fail, mock_response_ok])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        with patch("src.mailer.asyncio.sleep", new=AsyncMock()):
            mailer = ResendMailer(api_key="re_test", from_email="a@b.com", to_email="c@d.com")
            await mailer.send("subject", "<html/>")

    assert mock_client.post.await_count == 2
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_mailer.py -v
```

预期：`ModuleNotFoundError: No module named 'src.mailer'`。

- [ ] **Step 3: 实现 src/mailer.py**

```python
import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class Mailer(ABC):
    @abstractmethod
    async def send(self, subject: str, html: str) -> None:
        ...


class ResendMailer(Mailer):
    """通过 Resend API 发送邮件，带 2 次重试。"""

    def __init__(self, api_key: str, from_email: str, to_email: str, timeout: float = 30.0):
        self.api_key = api_key
        self.from_email = from_email
        self.to_email = to_email
        self.timeout = timeout

    async def send(self, subject: str, html: str) -> None:
        url = "https://api.resend.com/emails"
        payload = {
            "from": self.from_email,
            "to": [self.to_email],
            "subject": subject,
            "html": html,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    logger.info(f"Email sent to {self.to_email}: {resp.json()}")
                    return
            except Exception as e:
                last_exc = e
                logger.warning(f"Resend attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Resend send failed after retries: {last_exc}")
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_mailer.py -v
```

预期：2 个测试全部 PASSED。

- [ ] **Step 5: 提交**

```bash
git add src/mailer.py tests/test_mailer.py
git commit -m "feat(mailer): add ResendMailer with retry logic"
```

---

## Task 5: LLM 搜索 Provider（TDD）

**Files:**
- Create: `src/llm_search.py`
- Create: `tests/test_llm_search.py`

- [ ] **Step 1: 写失败的测试 tests/test_llm_search.py**

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm_search import GLMSearchProvider


SAMPLE_LLM_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    [
                        {
                            "name": "测试黑客松",
                            "organizer": "测试方",
                            "type_tag": "AI",
                            "summary": "简介",
                            "registration_deadline": "2026-08-01",
                            "start_date": "2026-08-15",
                            "end_date": "2026-08-17",
                            "location": "线上",
                            "registration_url": "https://example.com/register",
                            "detail_url": "https://example.com",
                        }
                    ],
                    ensure_ascii=False,
                )
            }
        }
    ]
}


@pytest.mark.asyncio
async def test_glm_search_parses_response():
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert result[0].name == "测试黑客松"
    assert result[0].registration_url == "https://example.com/register"


def test_parse_strips_markdown_codeblock():
    content = "```json\n" + json.dumps(
        [{"name": "X", "registration_url": "https://x.com"}], ensure_ascii=False
    ) + "\n```"
    result = GLMSearchProvider._parse(content)
    assert len(result) == 1
    assert result[0].name == "X"


def test_parse_skips_invalid_entries():
    content = json.dumps(
        [
            {"name": "OK", "registration_url": "https://ok.com"},
            {"name": "No URL"},  # 应被跳过
        ],
        ensure_ascii=False,
    )
    result = GLMSearchProvider._parse(content)
    assert len(result) == 1
    assert result[0].name == "OK"


def test_parse_raises_on_non_json():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="invalid JSON"):
        GLMSearchProvider._parse("not json at all")


def test_parse_raises_on_non_array():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="non-array"):
        GLMSearchProvider._parse(json.dumps({"not": "array"}))


@pytest.mark.asyncio
async def test_glm_search_retries_with_hint_on_json_error():
    """JSON 解析失败时，应附加 hint 重试一次。"""
    mock_response_bad = MagicMock()
    mock_response_bad.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    mock_response_bad.raise_for_status = MagicMock()

    mock_response_good = MagicMock()
    mock_response_good.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response_good.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_bad, mock_response_good])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert result[0].name == "测试黑客松"
    # 第二次调用应附加 hint
    assert mock_client.post.await_count == 2
    second_call_messages = mock_client.post.await_args_list[1].kwargs["json"]["messages"]
    from src.llm_search import JSON_HINT
    assert any(JSON_HINT in m.get("content", "") for m in second_call_messages)


@pytest.mark.asyncio
async def test_glm_search_returns_empty_list_after_hint_retry_fails():
    """JSON 解析在 hint 重试后仍失败，应返回空列表（静默跳过，不抛异常）。"""
    mock_response_bad = MagicMock()
    mock_response_bad.json.return_value = {"choices": [{"message": {"content": "still not json"}}]}
    mock_response_bad.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_bad, mock_response_bad])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert result == []
    assert mock_client.post.await_count == 2
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/test_llm_search.py -v
```

预期：`ModuleNotFoundError: No module named 'src.llm_search'`。

- [ ] **Step 3: 实现 src/llm_search.py**

```python
import asyncio
import json
import logging
from abc import ABC, abstractmethod

import httpx

from .models import Hackathon

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一名国内线上黑客松信息聚合助手。
任务：搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松、编程竞赛、创客马拉松。

筛选条件：
- 地域：中国大陆主办方或面向中国大陆参赛者
- 形式：必须是线上或含线上赛道
- 时间：报名截止日期 ≥ 今天，或比赛尚未结束
- 排除：纯线下赛事、已结束赛事、报名已截止赛事、无法获取报名链接的赛事

输出要求：
- 严格返回 JSON 数组，每个元素包含以下字段：
  - name: 赛事名称
  - organizer: 主办方
  - type_tag: 类型标签（如 AI/数据/全栈/创意）
  - summary: 一句话简介
  - registration_deadline: 报名截止日期 (YYYY-MM-DD 或 "待定")
  - start_date: 比赛开始日期 (YYYY-MM-DD 或 "待定")
  - end_date: 比赛结束日期 (YYYY-MM-DD 或 "待定")
  - location: "线上" 或包含线上描述
  - registration_url: 报名链接（必填）
  - detail_url: 官网或详情页链接（可选）
- 只返回 JSON，不包含 markdown 代码块标记或任何解释性文字
- 输出语言：中文

示例输出：
[
  {
    "name": "示例黑客松",
    "organizer": "示例主办方",
    "type_tag": "AI",
    "summary": "一句话简介",
    "registration_deadline": "2026-08-01",
    "start_date": "2026-08-15",
    "end_date": "2026-08-17",
    "location": "线上",
    "registration_url": "https://example.com/register",
    "detail_url": "https://example.com"
  }
]
"""

JSON_HINT = "请只返回合法 JSON 数组，不要包含任何 markdown 标记或解释性文字。"


class LLMSearchProvider(ABC):
    @abstractmethod
    async def search(self, today: str) -> list[Hackathon]:
        ...


class GLMSearchProvider(LLMSearchProvider):
    """通过智谱 GLM 联网搜索 API 获取黑客松列表。

    错误处理（匹配 spec 第 9 节）：
    - HTTP/网络错误：retry 2 次（指数退避 1s, 4s），仍失败 → 抛 RuntimeError → workflow 报错退出
    - JSON 解析错误：retry 1 次带 hint，仍失败 → 返回空列表 → main.py 跳过发送
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/",
        model: str = "glm-4-search",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def search(self, today: str) -> list[Hackathon]:
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"今天是 {today}。请搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松。"},
        ]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        last_http_exc: Exception | None = None
        json_hint_used = False

        for attempt in range(3):
            messages = list(base_messages)
            if json_hint_used:
                messages.append({"role": "user", "content": JSON_HINT})
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return self._parse(content)
            except ValueError as e:
                # JSON 解析错误：重试 1 次带 hint，仍失败则跳过当次发送（返回空列表）
                if not json_hint_used:
                    json_hint_used = True
                    logger.warning(f"JSON parse failed, will retry with hint: {e}")
                    continue
                logger.error(f"JSON parse failed after hint retry, skipping send: {e}")
                return []
            except Exception as e:
                # HTTP/网络错误：重试 2 次，指数退避
                last_http_exc = e
                logger.warning(f"GLM search attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"GLM search failed after retries: {last_http_exc}")

    @staticmethod
    def _parse(content: str) -> list[Hackathon]:
        """解析 LLM 返回的内容为 Hackathon 列表。"""
        text = content.strip()
        # 清理 markdown 代码块标记
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            arr = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}")

        if not isinstance(arr, list):
            raise ValueError("LLM returned non-array")

        result: list[Hackathon] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"Skip invalid hackathon entry: {e}")
        return result
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_llm_search.py -v
```

预期：7 个测试全部 PASSED。

- [ ] **Step 5: 运行全部测试**

```bash
pytest -v
```

预期：所有测试通过（test_models 4 + test_email_renderer 5 + test_mailer 2 + test_llm_search 7 = 18 个）。

- [ ] **Step 6: 提交**

```bash
git add src/llm_search.py tests/test_llm_search.py
git commit -m "feat(llm): add GLMSearchProvider with retry and JSON parsing"
```

---

## Task 6: 主入口编排

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: 实现 src/main.py**

```python
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .email_renderer import render_email
from .llm_search import GLMSearchProvider
from .mailer import ResendMailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def beijing_today() -> str:
    """返回北京时区的今日日期字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


async def main() -> int:
    load_dotenv()
    today = beijing_today()
    logger.info(f"Starting hackathon daily for {today}")

    # 1. 搜索
    provider = GLMSearchProvider(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
        model=os.environ.get("LLM_MODEL", "glm-4-search"),
    )
    try:
        hackathons = await provider.search(today)
    except Exception as e:
        logger.error(f"LLM search failed: {e}")
        return 1

    logger.info(f"Found {len(hackathons)} hackathons")
    if not hackathons:
        logger.info("No hackathons today, skip sending")
        return 0

    # 2. 渲染
    subject, html = render_email(hackathons, today)

    # 3. 发送
    mailer = ResendMailer(
        api_key=os.environ["RESEND_API_KEY"],
        from_email=os.environ["MAIL_FROM"],
        to_email=os.environ["MAIL_TO"],
    )
    try:
        await mailer.send(subject, html)
    except Exception as e:
        logger.error(f"Send email failed: {e}")
        return 1

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: 验证语法和导入**

```bash
python -c "from src.main import main, beijing_today; print(beijing_today())"
```

预期：输出今日日期，如 `2026-07-24`，且无 ImportError。

- [ ] **Step 3: 运行 ruff 检查**

```bash
ruff check src/ tests/
```

预期：`All checks passed!`

- [ ] **Step 4: 运行全部测试确保未破坏其他模块**

```bash
pytest -v
```

预期：18 个测试全部 PASSED。

- [ ] **Step 5: 提交**

```bash
git add src/main.py
git commit -m "feat(main): orchestrate search → render → send flow"
```

---

## Task 7: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/daily.yml`

- [ ] **Step 1: 实现 .github/workflows/daily.yml**

```yaml
name: Hackathon Daily

on:
  schedule:
    - cron: '0 0 * * *'  # UTC 00:00 = 北京 08:00
  workflow_dispatch:

jobs:
  send:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: requirements.txt

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tests
        run: pytest -v

      - name: Send daily email
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          LLM_BASE_URL: ${{ secrets.LLM_BASE_URL }}
          LLM_MODEL: ${{ secrets.LLM_MODEL }}
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          MAIL_FROM: ${{ secrets.MAIL_FROM }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
        run: python -m src.main
```

- [ ] **Step 2: 提交**

```bash
git add .github/workflows/daily.yml
git commit -m "ci: add GitHub Actions daily cron workflow"
```

---

## Task 8: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: 实现 README.md**

```markdown
# Hackathon Daily

每日 08:00（北京时间）自动推送国内线上黑客松信息到邮箱。

## 工作流程

1. GitHub Actions 定时触发（cron `0 0 * * *` = UTC 00:00 / 北京 08:00）
2. 调用 LLM 联网搜索 API（默认 GLM-4-search）获取当前可报名的线上黑客松
3. 渲染 HTML 邮件
4. 通过 Resend API 发送到收件箱

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
| `RESEND_API_KEY` | Resend API Key | `re_xxx` |
| `MAIL_FROM` | 发件人地址 | `Hackathon Daily <onboarding@resend.dev>` |
| `MAIL_TO` | 收件人地址 | `15720214985@163.com` |

## 手动触发 workflow

GitHub 仓库 → Actions → Hackathon Daily → Run workflow

## 技术栈

- Python 3.11
- httpx（异步 HTTP 客户端）
- Jinja2（模板引擎）
- Resend API（邮件发送）
- GitHub Actions（定时任务）

## 设计文档

详见 `docs/superpowers/specs/2026-07-24-hackathon-daily-design.md`
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```

---

## Task 9: 端到端验证（手动）

> 此任务依赖你已配置好 GitHub Secrets 并 push 到 GitHub。

- [ ] **Step 1: 推送到 GitHub**

```bash
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

- [ ] **Step 2: 在 GitHub 仓库配置 Secrets**

仓库 Settings → Secrets and variables → Actions → New repository secret，逐个添加：

- `LLM_API_KEY` = 你的 GLM API Key
- `RESEND_API_KEY` = 你的 Resend API Key
- `MAIL_FROM` = `Hackathon Daily <onboarding@resend.dev>`（或你验证过的发件域名）
- `MAIL_TO` = `15720214985@163.com`
- `LLM_BASE_URL` = `https://open.bigmodel.cn/api/paas/v4/`（可选）
- `LLM_MODEL` = `glm-4-search`（可选）

- [ ] **Step 3: 手动触发 workflow**

GitHub 仓库 → Actions → Hackathon Daily → Run workflow → 选择 main 分支 → Run

- [ ] **Step 4: 查看运行日志**

进入 Actions 运行详情，观察：
- [ ] `Run tests` 步骤应通过（18 个测试 PASSED）
- `Send daily email` 步骤应输出：
  - `Starting hackathon daily for 2026-07-24`
  - `Found N hackathons`
  - `Email sent to 15720214985@163.com: {...}`
  - `Done`

- [ ] **Step 5: 验证邮件**

打开 163 邮箱 `15720214985@163.com`，确认：
- 收到主题为 `黑客松日报 - 2026-07-24（N 场可报名）` 的邮件
- HTML 渲染正常（中文不乱码）
- 「立即报名」按钮链接可点击跳转
- 缺失字段正确显示为「待定」/「未知」

- [ ] **Step 6: 等待次日 cron 自动触发**

次日北京 08:00 左右（GitHub Actions 可能有 5-30 分钟延迟），再次收到邮件即验证 cron 生效。

---

## 验收清单（与 spec 第 14 节对应）

- [ ] Task 7: GitHub Actions workflow 能在 UTC 00:00 自动触发（cron 配置正确）
- [ ] Task 7: `workflow_dispatch` 能手动触发
- [ ] Task 5 + Task 6: LLM 调用成功，返回结构化 JSON 解析为 `List[Hackathon]`
- [ ] Task 9: 邮件成功送达 `15720214985@163.com`
- [ ] Task 3 + Task 9: 邮件 HTML 渲染正确，包含名称、类型、时间、报名链接
- [ ] Task 3: 缺失字段有兜底显示（测试覆盖）
- [ ] Task 6: 空结果时不发邮件，不报错（`main.py` 中 `if not hackathons: return 0`）
- [ ] Task 2-5: 全部单元测试通过（18 个）
- [ ] Task 8: README 说明如何配置 Secrets 和手动触发

---

## 备选方案：LLM Provider 切换

若 GLM-4-search 不可用或效果不佳，按以下步骤切换 Provider：

1. 在 `src/llm_search.py` 中新增一个 `XxxSearchProvider(LLMSearchProvider)` 类，实现 `search(today)` 方法
2. 在 `src/main.py` 中把 `GLMSearchProvider(...)` 替换为新类
3. 在 `.env.example` 和 GitHub Secrets 中更新 `LLM_BASE_URL` 和 `LLM_MODEL`
4. 重新触发 workflow 验证

由于 LLM 调用层已抽象为接口，切换不影响其他模块。
