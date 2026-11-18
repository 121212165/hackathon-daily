"""GLM 扇出多查询测试（网络调用全部 mock）。"""

from unittest.mock import AsyncMock

import pytest

from src.models import Hackathon
from src.providers.glm import QUERIES, GLMProvider, fanout_size


def _hackathon(name: str, url: str) -> Hackathon:
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


def _provider(monkeypatch, side_effect):
    provider = GLMProvider(api_key="test-key")
    provider._search_one = AsyncMock(side_effect=side_effect)
    return provider


def _clear_fanout(monkeypatch):
    monkeypatch.delenv("LLM_FANOUT", raising=False)


async def test_fanout_size_default_and_bounds(monkeypatch):
    _clear_fanout(monkeypatch)
    assert fanout_size() == 4
    monkeypatch.setenv("LLM_FANOUT", "1")
    assert fanout_size() == 1
    monkeypatch.setenv("LLM_FANOUT", "99")
    assert fanout_size() == len(QUERIES)
    monkeypatch.setenv("LLM_FANOUT", "bad")
    assert fanout_size() == 4


async def test_glm_fanout_default_uses_four_queries(monkeypatch):
    """默认 4 条查询并发执行。"""
    _clear_fanout(monkeypatch)
    provider = _provider(monkeypatch, lambda query, today: [_hackathon(query, f"https://e.com/{query}")])

    result = await provider.search("2026-11-18")

    assert len(result) == 4
    assert [call.args[0] for call in provider._search_one.await_args_list] == QUERIES[:4]


async def test_glm_fanout_one_is_current_behavior(monkeypatch):
    """LLM_FANOUT=1 → 只跑第一条查询，退回现状。"""
    monkeypatch.setenv("LLM_FANOUT", "1")
    provider = _provider(monkeypatch, lambda query, today: [_hackathon(query, "https://e.com/1")])

    result = await provider.search("2026-11-18")

    assert len(result) == 1
    provider._search_one.assert_awaited_once_with(QUERIES[0], "2026-11-18")


async def test_glm_single_query_failure_isolated(monkeypatch):
    """单查询失败只 warning，其余结果照常合并。"""
    _clear_fanout(monkeypatch)

    async def side_effect(query, today):
        if query == QUERIES[1]:
            raise RuntimeError("GLM 429")
        return [_hackathon(query, f"https://e.com/{query}")]

    provider = _provider(monkeypatch, side_effect)
    result = await provider.search("2026-11-18")

    assert len(result) == 3
    assert QUERIES[1] not in [h.name for h in result]


async def test_glm_dedups_across_queries(monkeypatch):
    """跨查询同一 URL（utm 差异）只保留一条。"""
    _clear_fanout(monkeypatch)
    provider = _provider(
        monkeypatch,
        lambda query, today: [
            _hackathon(query, "https://Example.com/reg/?utm_source=x"),
            _hackathon(query, "https://example.com/reg"),
        ],
    )

    result = await provider.search("2026-11-18")

    assert len(result) == 1


async def test_glm_all_queries_fail_raises(monkeypatch):
    _clear_fanout(monkeypatch)
    provider = _provider(
        monkeypatch,
        lambda query, today: (_ for _ in ()).throw(RuntimeError("down")),
    )

    with pytest.raises(RuntimeError, match="All GLM queries failed"):
        await provider.search("2026-11-18")
