from datetime import timedelta

import pytest

from src.models import Hackathon, beijing_date, is_broken_link


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


def _with_deadline(deadline: str) -> Hackathon:
    return Hackathon.from_dict(
        {"registration_url": "https://example.com", "registration_deadline": deadline}
    )


@pytest.mark.parametrize(
    ("days", "expected_left", "expected_urgency"),
    [
        (0, 0, "hot"),
        (3, 3, "hot"),
        (4, 4, "soon"),
        (7, 7, "soon"),
        (8, 8, "later"),
    ],
)
def test_days_left_and_urgency_boundaries(days, expected_left, expected_urgency):
    """边界：0/3 为 hot，4~7 为 soon，>7 为 later。"""
    deadline = (beijing_date() + timedelta(days=days)).isoformat()
    h = _with_deadline(deadline)
    assert h.days_left == expected_left
    assert h.urgency() == expected_urgency


@pytest.mark.parametrize("bad", ["待定", "", "  ", "2026/08/01", "not-a-date", None])
def test_days_left_invalid_returns_none_and_unknown(bad):
    """缺省 / 非法日期 → days_left=None，urgency=unknown。"""
    h = _with_deadline(bad)
    assert h.days_left is None
    assert h.urgency() == "unknown"


def test_past_deadline_is_hot():
    """已过期（days_left<0）仍落在 hot 档（≤3 天）。"""
    deadline = (beijing_date() - timedelta(days=1)).isoformat()
    assert _with_deadline(deadline).urgency() == "hot"


def test_derived_fields_do_not_change_from_dict_contract():
    """days_left 为纯派生属性，不进入构造参数 / from_dict 结果。"""
    h = _with_deadline("2026-08-01")
    assert "days_left" not in h.__dict__
    assert h.registration_deadline == "2026-08-01"


# ---------------- 无效链接判定 / 报名按钮回退 ----------------


@pytest.mark.parametrize(
    ("url", "broken"),
    [
        ("https://example.com/register", True),
        ("https://www.example.org/contest", True),
        ("http://localhost:3000/register", True),
        ("https://www.csu????.org/fullstack", True),
        ("javascript:alert(1)", True),
        ("/register", True),
        ("", True),
        (None, True),
        ("https://www.codefest.cn/register", False),
        ("www.codefest.cn/register", False),
        ("<https://www.codefest.cn/register>", False),
    ],
)
def test_is_broken_link(url, broken):
    assert is_broken_link(url) is broken


def test_register_link_prefers_registration_url():
    h = Hackathon(
        name="正常赛",
        organizer="方",
        type_tag="AI",
        summary="",
        registration_deadline="待定",
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url="https://www.codefest.cn/register",
        detail_url="https://www.codefest.cn",
    )
    assert h.register_link == "https://www.codefest.cn/register"


def test_register_link_falls_back_to_detail_url():
    h = Hackathon(
        name="占位赛",
        organizer="方",
        type_tag="AI",
        summary="",
        registration_deadline="待定",
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url="https://example.com/register",
        detail_url="https://www.official-site.cn/contest",
    )
    assert h.register_link == "https://www.official-site.cn/contest"


def test_register_link_empty_when_all_broken():
    h = Hackathon(
        name="死链赛",
        organizer="方",
        type_tag="AI",
        summary="",
        registration_deadline="待定",
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url="https://example.com/register",
        detail_url="https://example.org",
    )
    assert h.register_link == ""


def test_register_link_is_derived_not_stored():
    h = _with_deadline("2026-08-01")
    assert "register_link" not in h.__dict__
