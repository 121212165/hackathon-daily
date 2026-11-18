"""extract_json 测试：围栏剥离 + JSON 解析 + 逐条容错。"""

import json

import pytest

from src.providers._common import extract_json, parse_hackathons

VALID_ITEM = {
    "name": "测试赛",
    "organizer": "主办方",
    "registration_url": "https://example.com/reg",
}


def test_extract_json_with_fence():
    content = "```json\n" + json.dumps([VALID_ITEM], ensure_ascii=False) + "\n```"
    assert extract_json(content) == [VALID_ITEM]


def test_extract_json_plain_array():
    content = json.dumps([VALID_ITEM], ensure_ascii=False)
    assert extract_json(content) == [VALID_ITEM]


def test_extract_json_skips_invalid_entries():
    content = json.dumps([VALID_ITEM, {"name": "缺链接"}, "not-a-dict"], ensure_ascii=False)
    assert extract_json(content) == [VALID_ITEM]


def test_extract_json_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_json("这不是 JSON")


def test_extract_json_non_array_raises():
    with pytest.raises(ValueError, match="non-array"):
        extract_json('{"name": "x"}')


def test_parse_hackathons_reuses_extract_json():
    content = json.dumps([VALID_ITEM], ensure_ascii=False)
    parsed = parse_hackathons(content)
    assert len(parsed) == 1
    assert parsed[0].registration_url == VALID_ITEM["registration_url"]
