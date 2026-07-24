import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm_search import GLMSearchProvider

SAMPLE_LLM_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    [
                        {
                            "name": "测试黑客松",
                            "organizer": "测试方",
                            "type_tag": "AI",
                            "summary": "简介",
                            "registration_deadline": "2026-08-01",
                            "start_date": "2026-08-15",
                            "end_date": "2026-08-17",
                            "location": "线上",
                            "registration_url": "https://example.com/register",
                            "detail_url": "https://example.com",
                        }
                    ],
                    ensure_ascii=False,
                )
            }
        }
    ]
}


@pytest.mark.asyncio
async def test_glm_search_parses_response():
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert result[0].name == "测试黑客松"
    assert result[0].registration_url == "https://example.com/register"


def test_parse_strips_markdown_codeblock():
    content = "```json\n" + json.dumps(
        [{"name": "X", "registration_url": "https://x.com"}], ensure_ascii=False
    ) + "\n```"
    result = GLMSearchProvider._parse(content)
    assert len(result) == 1
    assert result[0].name == "X"


def test_parse_skips_invalid_entries():
    content = json.dumps(
        [
            {"name": "OK", "registration_url": "https://ok.com"},
            {"name": "No URL"},  # 应被跳过
        ],
        ensure_ascii=False,
    )
    result = GLMSearchProvider._parse(content)
    assert len(result) == 1
    assert result[0].name == "OK"


def test_parse_raises_on_non_json():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="invalid JSON"):
        GLMSearchProvider._parse("not json at all")


def test_parse_raises_on_non_array():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="non-array"):
        GLMSearchProvider._parse(json.dumps({"not": "array"}))


@pytest.mark.asyncio
async def test_glm_search_retries_with_hint_on_json_error():
    """JSON 解析失败时，应附加 hint 重试一次。"""
    mock_response_bad = MagicMock()
    mock_response_bad.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    mock_response_bad.raise_for_status = MagicMock()

    mock_response_good = MagicMock()
    mock_response_good.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response_good.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_bad, mock_response_good])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert result[0].name == "测试黑客松"
    # 第二次调用应附加 hint
    assert mock_client.post.await_count == 2
    second_call_messages = mock_client.post.await_args_list[1].kwargs["json"]["messages"]
    from src.llm_search import JSON_HINT
    assert any(JSON_HINT in m.get("content", "") for m in second_call_messages)


@pytest.mark.asyncio
async def test_glm_search_returns_empty_list_after_hint_retry_fails():
    """JSON 解析在 hint 重试后仍失败，应返回空列表（静默跳过，不抛异常）。"""
    mock_response_bad = MagicMock()
    mock_response_bad.json.return_value = {"choices": [{"message": {"content": "still not json"}}]}
    mock_response_bad.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_bad, mock_response_bad])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert result == []
    assert mock_client.post.await_count == 2
