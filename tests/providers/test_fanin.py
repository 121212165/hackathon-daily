"""FanIn 测试：并发合并 / URL 归一化去重 / 单源失败隔离 / 全失败抛错。"""

import asyncio
from unittest.mock import MagicMock

import pytest

from src.models import Hackathon
from src.providers.fanin import FanIn


def _hackathon(name: str, url: str = "https://example.com/reg") -> Hackathon:
    return Hackathon(
        name=name,
        organizer="主办方",
        type_tag="AI",
        summary="",
        registration_deadline="待定",
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url=url,
        detail_url=None,
    )


def _source(name: str, result=None, error: Exception | None = None):
    source = MagicMock()
    source.name = name

    async def search(today: str):
        if error is not None:
            raise error
        return result or []

    source.search = search
    return source


async def test_fanin_concurrent_merge():
    """所有源并发执行：两个源互相等待对方启动，串行实现会超时。"""
    started = 0
    both_started = asyncio.Event()

    async def search(name: str, today: str):
        nonlocal started
        started += 1
        if started >= 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1.0)
        return [_hackathon(name, f"https://example.com/{name}")]

    sources = []
    for name in ("a", "b"):
        source = MagicMock()
        source.name = name

        async def run(today: str, _name=name):
            return await search(_name, today)

        source.search = run
        sources.append(source)

    result = await asyncio.wait_for(FanIn(sources).search("2026-11-18"), timeout=2.0)
    assert {h.name for h in result} == {"a", "b"}


async def test_fanin_dedup_by_normalized_url():
    """URL 带 utm / 大小写 / 尾斜杠差异 → 合并后只保留一条。"""
    source_a = _source("a", [
        _hackathon("原名", "HTTPS://Example.com/reg/?utm_source=x"),
        _hackathon("独立赛事", "https://example.com/other"),
    ])
    source_b = _source("b", [
        _hackathon("改了标题", "https://example.com/reg?utm_campaign=y"),
    ])

    result = await FanIn([source_a, source_b]).search("2026-11-18")

    assert len(result) == 2
    assert {h.name for h in result} == {"原名", "独立赛事"}


async def test_fanin_invalid_url_falls_back_to_title():
    """非法 URL 用标题 hash 去重；标题不同则都保留。"""
    source_a = _source("a", [_hackathon("赛事甲", "javascript:alert(1)")])
    source_b = _source("b", [
        _hackathon("赛事甲", "not-a-url"),
        _hackathon("赛事乙", ""),
    ])

    result = await FanIn([source_a, source_b]).search("2026-11-18")

    assert [h.name for h in result] == ["赛事甲", "赛事乙"]


async def test_fanin_single_source_failure_isolated():
    """单源失败只 warning，其它源结果照常返回。"""
    broken = _source("broken", error=RuntimeError("API 500"))
    good = _source("good", [_hackathon("A")])

    result = await FanIn([broken, good]).search("2026-11-18")

    assert [h.name for h in result] == ["A"]
    assert all(h.source == "good" for h in result)


async def test_fanin_all_fail_raises_with_summaries():
    """全部源失败 → RuntimeError 含逐源错误摘要。"""
    sources = [
        _source("a", error=RuntimeError("boom A")),
        _source("b", error=ValueError("boom B")),
    ]

    with pytest.raises(RuntimeError, match="All search sources failed") as exc:
        await FanIn(sources).search("2026-11-18")

    assert "a: boom A" in str(exc.value)
    assert "b: boom B" in str(exc.value)


async def test_fanin_empty_results_are_ok():
    """全部源成功但无结果 → 返回空列表，不抛错（今日无新增）。"""
    result = await FanIn([_source("a"), _source("b")]).search("2026-11-18")
    assert result == []


async def test_fanin_invalid_result_is_failure():
    """源返回非 list → 视作失败；全部如此仍抛错。"""
    source = MagicMock()
    source.name = "broken"

    async def search(today: str):
        return None

    source.search = search
    with pytest.raises(RuntimeError, match="invalid result type"):
        await FanIn([source]).search("2026-11-18")


async def test_fanin_requires_sources():
    with pytest.raises(ValueError, match="at least one search source"):
        FanIn([])
