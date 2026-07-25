import json
from pathlib import Path

from src.email_renderer import render_email, safe_url
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
    hackathons = [Hackathon.from_dict({"registration_url": "https://example.com/only"})]
    _, html = render_email(hackathons, "2026-07-24")
    # from_dict 默认填充：organizer/type_tag="未知"，deadline/start/end="待定"
    assert "待定" in html
    assert "未知" in html
    assert "https://example.com/only" in html


def test_render_email_displays_today():
    hackathons = _load_fixture()
    _, html = render_email(hackathons, "2026-07-24")
    assert "2026-07-24" in html


def test_render_email_buttons_have_absolute_href():
    """邮件按钮的 href 必须是 http/https 绝对链接，确保在邮件客户端可点击跳转。"""
    hackathons = _load_fixture()
    _, html = render_email(hackathons, "2026-07-24")
    # 立即报名按钮
    assert 'href="https://example.com/register"' in html
    # 详情按钮
    assert 'href="https://example.com"' in html


# ---------------- safe_url 单元测试 ----------------


def test_safe_url_https_passthrough():
    assert safe_url("https://example.com/register") == "https://example.com/register"


def test_safe_url_http_passthrough():
    assert safe_url("http://example.com") == "http://example.com"


def test_safe_url_adds_https_to_bare_domain():
    """LLM 常见错误：返回 www.xxx 或 xxx.yyy 不带 scheme，必须补 https://。"""
    assert safe_url("www.example.com") == "https://www.example.com"
    assert safe_url("example.com") == "https://example.com"
    assert safe_url("example.com/path?a=1") == "https://example.com/path?a=1"
    assert safe_url("sub.domain.com/register") == "https://sub.domain.com/register"


def test_safe_url_strips_whitespace():
    assert safe_url("  https://example.com  ") == "https://example.com"
    assert safe_url("\nwww.example.com\n") == "https://www.example.com"


def test_safe_url_extracts_markdown_link():
    """LLM 偶尔会返回 [文字](url) 形式，需提取出真实 URL。"""
    assert safe_url("[报名](https://example.com/register)") == "https://example.com/register"
    assert safe_url("[点击](www.example.com)") == "https://www.example.com"


def test_safe_url_strips_angle_brackets():
    assert safe_url("<https://example.com>") == "https://example.com"
    assert safe_url("<www.example.com>") == "https://www.example.com"


def test_safe_url_blocks_dangerous_schemes():
    assert safe_url("javascript:alert(1)") == "#"
    assert safe_url("data:text/html,<script>") == "#"
    assert safe_url("vbscript:msgbox") == "#"


def test_safe_url_blocks_relative_paths():
    """相对路径在邮件客户端会指向邮件 viewer 自身域名，必须屏蔽。"""
    assert safe_url("/register") == "#"
    assert safe_url("../foo") == "#"
    assert safe_url("register") == "#"


def test_safe_url_handles_empty_and_none():
    assert safe_url("") == "#"
    assert safe_url(None) == "#"
    assert safe_url("   ") == "#"


def test_safe_url_preserves_query_and_fragment():
    assert safe_url("https://example.com/r?a=1&b=2") == "https://example.com/r?a=1&b=2"
    assert safe_url("https://example.com/r#section") == "https://example.com/r#section"
