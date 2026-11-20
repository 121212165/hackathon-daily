import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.email_renderer import render_email, render_empty_email, safe_url
from src.models import Hackathon, beijing_date

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture() -> list[Hackathon]:
    data = json.loads((FIXTURES / "sample_hackathons.json").read_text(encoding="utf-8"))
    return [Hackathon.from_dict(item) for item in data]


def _h(name: str, days: int | None, type_tag: str = "AI") -> Hackathon:
    """构造相对今天截止的赛事；days=None 表示无有效截止日期。"""
    deadline = (beijing_date() + timedelta(days=days)).isoformat() if days is not None else "待定"
    return Hackathon(
        name=name,
        organizer="主办方",
        type_tag=type_tag,
        summary="一句话简介",
        registration_deadline=deadline,
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url=f"https://www.codefest.cn/{name}",
        detail_url=None,
    )


def test_render_email_contains_name_and_url():
    hackathons = _load_fixture()
    subject, html, _ = render_email(hackathons, "2026-07-24")
    assert "示例AI黑客松" in html
    assert "https://www.codefest.cn/register" in html
    assert "极简赛事" in html
    assert "https://www.codefest.cn/minimal" in html


def test_render_email_subject_format():
    hackathons = _load_fixture()
    subject, _, _ = render_email(hackathons, "2026-07-24")
    assert subject == "黑客松日报 - 2026-07-24（2 场可报名）"


def test_render_email_displays_dates():
    hackathons = _load_fixture()
    _, html, _ = render_email(hackathons, "2026-07-24")
    assert "2026-08-01" in html
    assert "2026-08-15" in html
    assert "2026-08-17" in html


def test_render_email_handles_missing_fields():
    hackathons = [Hackathon.from_dict({"registration_url": "https://www.codefest.cn/only"})]
    _, html, _ = render_email(hackathons, "2026-07-24")
    # from_dict 默认填充：organizer/type_tag="未知"，deadline/start/end="待定"
    assert "待定" in html
    assert "未知" in html
    assert "https://www.codefest.cn/only" in html


def test_render_email_displays_today():
    hackathons = _load_fixture()
    _, html, _ = render_email(hackathons, "2026-07-24")
    assert "2026-07-24" in html


def test_render_email_buttons_have_absolute_href():
    """邮件按钮的 href 必须是 http/https 绝对链接，确保在邮件客户端可点击跳转。"""
    hackathons = _load_fixture()
    _, html, _ = render_email(hackathons, "2026-07-24")
    # 立即报名按钮
    assert 'href="https://www.codefest.cn/register"' in html
    # 详情按钮
    assert 'href="https://www.codefest.cn"' in html


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


def test_safe_url_strips_control_characters():
    """控制字符（\\t\\n\\r 等）应被过滤，防止污染邮件 href 属性。"""
    # 控制字符被去除后保留合法 URL
    assert safe_url("https://example.com/register\n") == "https://example.com/register"
    assert safe_url("https://example.com/a\tb") == "https://example.com/ab"
    assert safe_url("https://example.com\r\n") == "https://example.com"
    # 含 onclick 注入企图的 URL：控制字符被剥，保留原 URL 文本（autoescape 会处理 HTML 字符）
    assert (
        safe_url("https://example.com\tonclick=alert(1)") == "https://example.comonclick=alert(1)"
    )


# ---------------- 批次 2：排序 / 分组 / 统计 / 文本版 ----------------


def test_render_email_sorts_by_days_left_none_last():
    """days_left 升序；无截止日期（None）排最后。"""
    items = [_h("C_later", 30), _h("D_unknown", None), _h("B_soon", 7), _h("A_hot", 1)]
    _, html, _ = render_email(items, "2026-11-18")
    positions = {name: html.index(name) for name in ("A_hot", "B_soon", "C_later", "D_unknown")}
    assert positions["A_hot"] < positions["B_soon"] < positions["C_later"] < positions["D_unknown"]


def test_render_email_group_order_and_headers():
    """分组小节按 hot → soon → later 顺序出现。"""
    items = [_h("C_later", 30), _h("B_soon", 5), _h("A_hot", 2)]
    _, html, _ = render_email(items, "2026-11-18")
    hot = html.index("🔥 即将截止 (≤3 天)")
    soon = html.index("📌 本周 (≤7 天)")
    later = html.index("📅 后续")
    assert hot < soon < later


def test_render_email_stats_bar():
    """统计条：今日新增 5 · 即将截止 2 · 本周累计 3。"""
    items = [_h("a", 1), _h("b", 3), _h("c", 7), _h("d", 30), _h("e", None)]
    _, html, _ = render_email(items, "2026-11-18")
    assert re.search(r">5</div>\s*<div[^>]*>\s*今日新增", html)
    assert re.search(r">2</div>\s*<div[^>]*>\s*即将截止", html)
    assert re.search(r">3</div>\s*<div[^>]*>\s*本周累计", html)


def test_render_email_text_version():
    """纯文本版：- 列表 + 截止日期前缀，排序与 HTML 一致。"""
    items = [_h("热赛事", 1), _h("晚赛事", 30)]
    subject, html, text = render_email(items, "2026-11-18")
    assert subject == "黑客松日报 - 2026-11-18（2 场可报名）"
    assert "- [截止 " in text
    assert "今日新增 2 场" in text
    assert "报名: https://www.codefest.cn/" in text
    assert text.index("热赛事") < text.index("晚赛事")
    assert "热赛事" in html


def test_render_email_dark_mode_badges_and_width():
    """600px 居中、明暗模式 meta+media+!important、红黄绿徽章。"""
    items = [_h("hot", 1), _h("soon", 5), _h("later", 30), _h("unknown", None)]
    _, html, _ = render_email(items, "2026-11-18")
    assert 'name="color-scheme" content="light dark"' in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "!important" in html
    assert "max-width: 600px" in html
    for badge in ("badge-hot", "badge-soon", "badge-later", "badge-unknown"):
        assert badge in html
    assert "flex" not in html.lower()


def test_render_email_keeps_autoescape():
    """autoescape 保留：恶意标题不应注入 HTML。"""
    _, html, _ = render_email([_h("<script>alert(1)</script>", 1)], "2026-11-18")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_empty_email():
    """空日邮件：今日无新增 + 本周累计 + 即将截止 TOP3（HTML 与文本）。"""
    subject, html, text = render_empty_email([_h("TOP1", 1), _h("TOP2", 2)], 9, "2026-11-18")
    assert subject == "黑客松日报 - 2026-11-18（今日无新增）"
    assert "今日无新增" in html
    assert "本周累计 9 场" in html
    assert "即将截止 TOP3" in html
    assert "TOP1" in html and "TOP2" in html
    assert "本周累计 9 场" in text
    assert "- [截止 " in text and "TOP1" in text


# ---------------- A/B：收敛版（style="calm"）----------------


def test_render_email_calm_variant():
    """收敛版：保留酸性色 + 等宽标签，去掉故障投影 / 网格 / 硬阴影，但链接仍安全。"""
    items = [_h("热赛事", 1), _h("晚赛事", 30)]
    subject, html, text = render_email(items, "2026-11-18", style="calm")
    assert subject == "黑客松日报 - 2026-11-18（2 场可报名）"
    assert "#D4FF00" in html
    assert "IBM Plex Mono" in html
    assert "text-shadow" not in html
    assert "repeating-linear-gradient" not in html
    assert "box-shadow" not in html
    assert 'href="https://www.codefest.cn/热赛事"' in html
    assert "热赛事" in text


def test_render_email_bold_is_default():
    """不传 style 时仍是原来的酸性粗野版（向后兼容）。"""
    _, html, _ = render_email([_h("A", 1)], "2026-11-18")
    assert "text-shadow" in html
    assert "repeating-linear-gradient" in html
    assert "#D4FF00" in html


def test_render_email_invalid_style():
    with pytest.raises(ValueError, match="unknown email style"):
        render_email([], "2026-11-18", style="loud")


def test_render_empty_email_calm_variant():
    """空日收敛版：同样保留酸性色 + 等宽标签，内容齐全。"""
    subject, html, text = render_empty_email(
        [_h("TOP1", 1), _h("TOP2", 2)], 9, "2026-11-18", style="calm"
    )
    assert subject == "黑客松日报 - 2026-11-18（今日无新增）"
    assert "#D4FF00" in html
    assert "IBM Plex Mono" in html
    assert "text-shadow" not in html
    assert "repeating-linear-gradient" not in html
    assert "今日无新增" in html
    assert "本周累计 9 场" in html
    assert "即将截止 TOP3" in html
    assert "TOP1" in html and "TOP2" in html
    assert "TOP1" in text


# ---------------- 无效报名链接 → 回退赛事官网 ----------------


def _h_with_urls(name: str, reg_url: str, detail_url: str | None) -> Hackathon:
    return Hackathon(
        name=name,
        organizer="主办方",
        type_tag="AI",
        summary="",
        registration_deadline=(beijing_date() + timedelta(days=1)).isoformat(),
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url=reg_url,
        detail_url=detail_url,
    )


def test_register_button_falls_back_to_official_site():
    """报名链接是 example.com 占位符时，「立即报名」跳到赛事官网 detail_url。"""
    h = _h_with_urls(
        "占位链接赛", "https://example.com/register", "https://www.official-site.cn/contest"
    )
    _, html, text = render_email([h], "2026-11-20")
    assert 'href="https://www.official-site.cn/contest"' in html
    assert "https://example.com" not in html
    assert "报名: https://www.official-site.cn/contest" in text


def test_register_button_hidden_when_no_usable_link():
    """两个链接都无效时不渲染死链按钮。"""
    h = _h_with_urls("死链赛", "https://example.com/register", "https://example.org")
    _, html, text = render_email([h], "2026-11-20")
    assert "立即报名" not in html
    assert "详情" not in html
    assert "报名: " not in text


def test_detail_button_hidden_when_fallback_reuses_official_site():
    """回退到官网后不再重复渲染同一个「详情」按钮。"""
    h = _h_with_urls("单链接赛", "https://example.com/register", "https://www.official-site.cn")
    _, html, _ = render_email([h], "2026-11-20")
    assert html.count('href="https://www.official-site.cn"') == 1


def test_register_button_prefers_valid_registration_url():
    """报名链接有效时仍优先跳报名页，「详情」按钮保留。"""
    h = _h_with_urls("正常赛", "https://www.codefest.cn/register", "https://www.codefest.cn")
    _, html, _ = render_email([h], "2026-11-20")
    assert 'href="https://www.codefest.cn/register"' in html
    assert 'href="https://www.codefest.cn"' in html


@pytest.mark.parametrize("style", ["bold", "calm"])
def test_empty_email_register_button_uses_fallback(style):
    """空日邮件 TOP3 同样用官网链接替换占位报名链接（两种风格）。"""
    h = _h_with_urls(
        "TOP占位", "https://example.com/register", "https://www.official-site.cn/contest"
    )
    _, html, _ = render_empty_email([h], 3, "2026-11-20", style=style)
    assert 'href="https://www.official-site.cn/contest"' in html
    assert "https://example.com" not in html
