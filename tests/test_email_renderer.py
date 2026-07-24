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
