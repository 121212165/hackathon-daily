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
