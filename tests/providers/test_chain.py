"""ProviderChain 测试：多 Provider 容错 fallback。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import Hackathon
from src.providers.chain import ProviderChain, build_provider_chain


def _make_hackathon(name="测试"):
    return Hackathon(
        name=name,
        organizer="主办方",
        type_tag="AI",
        summary="",
        registration_deadline="待定",
        start_date="待定",
        end_date="待定",
        location="线上",
        registration_url="https://example.com",
        detail_url=None,
    )


async def test_chain_first_provider_success():
    """首个 provider 成功 → 不调后续。"""
    p1 = MagicMock()
    p1.name = "glm"
    p1.search = AsyncMock(return_value=[_make_hackathon("A")])
    p2 = MagicMock()
    p2.name = "openai"
    p2.search = AsyncMock(return_value=[])

    chain = ProviderChain([p1, p2])
    result = await chain.search("2026-08-03")

    assert len(result) == 1
    p1.search.assert_awaited_once()
    p2.search.assert_not_awaited()
    assert result[0].source == "glm"


async def test_chain_fallback_on_failure():
    """首个失败 → fallback 到第二个。"""
    p1 = MagicMock()
    p1.name = "glm"
    p1.search = AsyncMock(side_effect=RuntimeError("GLM 400"))
    p2 = MagicMock()
    p2.name = "openai"
    p2.search = AsyncMock(return_value=[_make_hackathon("B")])

    chain = ProviderChain([p1, p2])
    result = await chain.search("2026-08-03")

    assert len(result) == 1
    p1.search.assert_awaited_once()
    p2.search.assert_awaited_once()
    assert result[0].source == "openai"


async def test_chain_all_fail_raises():
    """全部失败 → 抛 RuntimeError 含所有错误。"""
    p1 = MagicMock()
    p1.name = "glm"
    p1.search = AsyncMock(side_effect=RuntimeError("GLM down"))
    p2 = MagicMock()
    p2.name = "openai"
    p2.search = AsyncMock(side_effect=RuntimeError("OpenAI down"))

    chain = ProviderChain([p1, p2])
    with pytest.raises(RuntimeError, match="All providers failed"):
        await chain.search("2026-08-03")


async def test_chain_empty_providers_raises():
    """空 provider 列表 → 构造时抛 ValueError。"""
    with pytest.raises(ValueError, match="at least one provider"):
        ProviderChain([])


async def test_chain_source_tagging():
    """成功 provider 的 name 标记到 hackathon.source。"""
    p1 = MagicMock()
    p1.name = "glm"
    items = [_make_hackathon("A"), _make_hackathon("B")]
    p1.search = AsyncMock(return_value=items)

    chain = ProviderChain([p1])
    result = await chain.search("2026-08-03")

    assert all(h.source == "glm" for h in result)


def _clear_provider_env(monkeypatch):
    """清空所有 provider 相关环境变量，避免宿主环境残留影响断言。"""
    for name in ("LLM_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDERS"):
        monkeypatch.delenv(name, raising=False)


async def test_build_chain_openai_key_only(monkeypatch):
    """只配 OPENAI_API_KEY、LLM_PROVIDERS 用默认 "glm" → 兜底仍能建链（0.2 验收）。"""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")

    chain = build_provider_chain()

    assert [p.name for p in chain.providers] == ["openai"]


async def test_build_chain_no_key_raises(monkeypatch):
    """一个 key 都没配 → 仍抛 ValueError（保持现状语义）。"""
    _clear_provider_env(monkeypatch)

    with pytest.raises(ValueError, match="No LLM provider available"):
        build_provider_chain()
