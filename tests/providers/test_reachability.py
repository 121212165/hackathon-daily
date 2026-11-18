"""最小可达性验证（批次 1 / §4.2 endpoint 探测纪律）。

默认全部 skip：仅在显式设置 LIVE_REACHABILITY=1 或配置对应 key 时才联网，
用于在接入新源前确认返回结构。单元测试的解析逻辑见 test_providers.py。
"""

import os

import httpx
import pytest

LIVE = os.environ.get("LIVE_REACHABILITY") == "1"
skip_unless_live = pytest.mark.skipif(not LIVE, reason="需设置 LIVE_REACHABILITY=1 才联网")
skip_without_clist = pytest.mark.skipif(
    not (os.environ.get("CLIST_USERNAME") and os.environ.get("CLIST_API_KEY")),
    reason="需 CLIST_USERNAME / CLIST_API_KEY",
)
skip_without_serper = pytest.mark.skipif(
    not os.environ.get("SERPER_API_KEY"), reason="需 SERPER_API_KEY"
)
skip_without_tavily = pytest.mark.skipif(
    not os.environ.get("TAVILY_API_KEY"), reason="需 TAVILY_API_KEY"
)


@skip_unless_live
def test_devpost_reachable_or_antibot():
    """devpost.com/hackathons：预期 200（可解析）或 403（已知反爬，跳过该源）。"""
    resp = httpx.get(
        "https://devpost.com/hackathons",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20.0,
        follow_redirects=True,
    )
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert "hackathon" in resp.text.lower()


@skip_unless_live
def test_mlh_inertia_blob():
    """mlh.io/events：确认 Inertia JSON 含 upcomingEvents。"""
    resp = httpx.get("https://mlh.io/events", timeout=20.0, follow_redirects=True)
    assert resp.status_code == 200
    assert "upcomingEvents" in resp.text


@skip_without_clist
def test_clist_api_shape():
    resp = httpx.get(
        "https://clist.by/api/v4/contest/",
        params={
            "username": os.environ["CLIST_USERNAME"],
            "api_key": os.environ["CLIST_API_KEY"],
            "limit": 1,
        },
        timeout=20.0,
    )
    assert resp.status_code == 200
    assert "objects" in resp.json()


@skip_without_serper
def test_serper_api_shape():
    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"]},
        json={"q": "线上黑客松", "num": 1},
        timeout=20.0,
    )
    assert resp.status_code == 200
    assert "organic" in resp.json()


@skip_without_tavily
def test_tavily_api_shape():
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": os.environ["TAVILY_API_KEY"],
            "query": "线上黑客松",
            "max_results": 1,
            "search_depth": "basic",
        },
        timeout=20.0,
    )
    assert resp.status_code == 200
    assert "results" in resp.json()
