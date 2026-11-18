"""结构化源 / SERP 源测试：无 key 跳过 + 解析容错（网络调用全部 mock）。"""

import json
from unittest.mock import AsyncMock

import pytest

from src.providers.clist import ClistProvider
from src.providers.devpost import DevpostProvider
from src.providers.mlh import MLHProvider
from src.providers.serper import SerperProvider
from src.providers.tavily import TavilyProvider

VALID = {
    "name": "线上 AI 黑客松",
    "organizer": "主办方",
    "type_tag": "AI",
    "summary": "简介",
    "registration_deadline": "2026-12-01",
    "start_date": "2026-12-10",
    "end_date": "2026-12-12",
    "location": "线上",
    "registration_url": "https://example.com/reg",
    "detail_url": "https://example.com",
}


class FakeResponse:
    def __init__(self, json_data=None, text="", error=None):
        self._json_data = json_data
        self.text = text
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._json_data


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


def _patch_client(monkeypatch, module: str, response):
    client = FakeClient(response)
    monkeypatch.setattr(f"{module}.httpx.AsyncClient", lambda **kwargs: client)
    return client


def _clear_keys(monkeypatch):
    for name in (
        "SERPER_API_KEY",
        "TAVILY_API_KEY",
        "CLIST_USERNAME",
        "CLIST_API_KEY",
        "DEVPOST_ENABLED",
        "MLH_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


async def test_providers_without_keys_are_skipped(monkeypatch):
    """需 key 的源无 key → from_env() 返回 None；免 key 源默认可用、可显式禁用。"""
    _clear_keys(monkeypatch)

    assert ClistProvider.from_env() is None
    assert SerperProvider.from_env() is None
    assert TavilyProvider.from_env() is None
    assert isinstance(DevpostProvider.from_env(), DevpostProvider)
    assert isinstance(MLHProvider.from_env(), MLHProvider)

    monkeypatch.setenv("DEVPOST_ENABLED", "0")
    monkeypatch.setenv("MLH_ENABLED", "false")
    assert DevpostProvider.from_env() is None
    assert MLHProvider.from_env() is None


async def test_devpost_parses_jsonld(monkeypatch):
    event = {
        "name": "Devpost Hackathon",
        "url": "https://devpost.com/hackathons/ai-hack-2026",
        "description": "线上 AI 赛",
        "startDate": "2026-12-01",
    }
    page = (
        '<script type="application/ld+json">'
        + json.dumps({"@type": "Event", **event})
        + "</script>"
    )
    _patch_client(monkeypatch, "src.providers.devpost", FakeResponse(text=page))

    result = await DevpostProvider().search("2026-11-18")

    assert [h.name for h in result] == ["Devpost Hackathon"]
    assert result[0].registration_url == event["url"]


async def test_devpost_parses_card_links(monkeypatch):
    page = '<a href="https://devpost.com/hackathons/demo?ref=x"><h4>卡片赛事</h4></a>'
    _patch_client(monkeypatch, "src.providers.devpost", FakeResponse(text=page))

    result = await DevpostProvider().search("2026-11-18")

    assert [h.name for h in result] == ["卡片赛事"]
    assert result[0].registration_url == "https://devpost.com/hackathons/demo"


async def test_devpost_anti_bot_is_skipped(monkeypatch):
    _patch_client(
        monkeypatch,
        "src.providers.devpost",
        FakeResponse(error=RuntimeError("403 Forbidden")),
    )
    assert await DevpostProvider().search("2026-11-18") == []


async def test_devpost_unparseable_page_is_skipped(monkeypatch):
    _patch_client(monkeypatch, "src.providers.devpost", FakeResponse(text="<html>403</html>"))
    assert await DevpostProvider().search("2026-11-18") == []


async def test_mlh_parses_inertia_blob(monkeypatch):
    blob = {
        "component": "SeasonEvents/Index",
        "props": {
            "upcomingEvents": [
                {
                    "name": "MLH Online Hack",
                    "url": "/events/online-hack/prizes",
                    "websiteUrl": "https://example.com/mlh",
                    "startsAt": "2026-12-01T10:00:00Z",
                    "endsAt": "2026-12-02T10:00:00Z",
                    "location": "Everywhere, Worldwide",
                    "formatLabel": "Digital",
                    "customFields": {"hackathon_focus": ["AI"]},
                },
                {"no_name": True},
            ]
        },
    }
    page = f'<script data-page="app" type="application/json">{json.dumps(blob)}</script>'
    _patch_client(monkeypatch, "src.providers.mlh", FakeResponse(text=page))

    result = await MLHProvider().search("2026-11-18")

    assert len(result) == 1
    assert result[0].name == "MLH Online Hack"
    assert result[0].registration_url == "https://example.com/mlh"
    assert result[0].detail_url == "https://www.mlh.com/events/online-hack/prizes"
    assert result[0].start_date == "2026-12-01"


async def test_mlh_structure_change_is_skipped(monkeypatch):
    _patch_client(monkeypatch, "src.providers.mlh", FakeResponse(text="<html>changed</html>"))
    assert await MLHProvider().search("2026-11-18") == []


async def test_clist_parses_objects(monkeypatch):
    data = {
        "objects": [
            {
                "event": "clist 编程赛",
                "host": "clist",
                "url": "https://clist.by/contest/1/",
                "start": "2026-12-01T00:00:00",
                "end": "2026-12-02T00:00:00",
            },
            {"id": 2},  # 缺 name → 跳过
        ]
    }
    client = _patch_client(monkeypatch, "src.providers.clist", FakeResponse(json_data=data))

    result = await ClistProvider("user", "key").search("2026-11-18")

    assert [h.name for h in result] == ["clist 编程赛"]
    assert client.calls[0][2]["params"]["api_key"] == "key"


async def test_clist_bad_response_is_skipped(monkeypatch):
    _patch_client(monkeypatch, "src.providers.clist", FakeResponse(json_data={"unexpected": 1}))
    assert await ClistProvider("user", "key").search("2026-11-18") == []


async def test_serper_uses_llm_structuring(monkeypatch):
    response = {
        "organic": [
            {"title": "A", "link": "https://a.example", "snippet": "线上黑客松"},
            {"title": "B", "snippet": "无链接应丢弃"},
        ]
    }
    _patch_client(monkeypatch, "src.providers.serper", FakeResponse(json_data=response))
    structure = AsyncMock(return_value=[VALID])
    monkeypatch.setattr("src.providers.serper.structure_search_results", structure)

    result = await SerperProvider("key").search("2026-11-18")

    assert len(result) == 1
    assert result[0].registration_url == VALID["registration_url"]
    snippets = structure.await_args.args[0]
    assert snippets == [{"title": "A", "link": "https://a.example", "snippet": "线上黑客松"}]


async def test_serper_no_organic_is_skipped(monkeypatch):
    _patch_client(monkeypatch, "src.providers.serper", FakeResponse(json_data={}))
    assert await SerperProvider("key").search("2026-11-18") == []


async def test_tavily_uses_llm_structuring(monkeypatch):
    response = {
        "results": [
            {"title": "A", "url": "https://a.example", "content": "报名链接..."},
        ]
    }
    client = _patch_client(monkeypatch, "src.providers.tavily", FakeResponse(json_data=response))
    structure = AsyncMock(return_value=[VALID])
    monkeypatch.setattr("src.providers.tavily.structure_search_results", structure)

    result = await TavilyProvider("key").search("2026-11-18")

    assert len(result) == 1
    assert client.calls[0][2]["json"]["search_depth"] == "basic"
    assert structure.await_args.args[0][0]["content"] == "报名链接..."


@pytest.mark.parametrize("module, factory", [
    ("src.providers.serper", lambda: SerperProvider("key")),
    ("src.providers.tavily", lambda: TavilyProvider("key")),
])
async def test_serp_api_failure_is_skipped(monkeypatch, module, factory):
    _patch_client(monkeypatch, module, FakeResponse(error=RuntimeError("network down")))
    assert await factory().search("2026-11-18") == []
