import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


async def test_glm_search_parses_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
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
    content = (
        "```json\n"
        + json.dumps([{"name": "X", "registration_url": "https://x.com"}], ensure_ascii=False)
        + "\n```"
    )
    result = GLMSearchProvider._parse(content)
    assert len(result) == 1
    assert result[0].name == "X"


def test_parse_strips_single_line_codeblock():
    """单行 ```json [...] ``` 也应被正确剥离。"""
    content = (
        "```json"
        + json.dumps([{"name": "X", "registration_url": "https://x.com"}], ensure_ascii=False)
        + "```"
    )
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
    with pytest.raises(ValueError, match="invalid JSON"):
        GLMSearchProvider._parse("not json at all")


def test_parse_raises_on_non_array():
    with pytest.raises(ValueError, match="non-array"):
        GLMSearchProvider._parse(json.dumps({"not": "array"}))


async def test_glm_search_retries_with_hint_on_json_error():
    """JSON 解析失败时，应附加 hint 重试一次。"""
    mock_response_bad = MagicMock()
    mock_response_bad.status_code = 200
    mock_response_bad.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    mock_response_bad.raise_for_status = MagicMock()

    mock_response_good = MagicMock()
    mock_response_good.status_code = 200
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


async def test_glm_search_returns_empty_list_after_hint_retry_fails():
    """JSON 解析在 hint 重试后仍失败，应返回空列表（静默跳过，不抛异常）。"""
    mock_response_bad = MagicMock()
    mock_response_bad.status_code = 200
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


async def test_glm_search_retries_on_http_error_then_raises():
    """HTTP/网络错误重试 2 次（共 3 次尝试），仍失败抛 RuntimeError。"""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        with patch("src.llm_search.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="GLM search failed after retries"):
                provider = GLMSearchProvider(
                    api_key="test", base_url="https://api.test.com", model="test"
                )
                await provider.search("2026-07-24")

    assert mock_client.post.await_count == 3


async def test_glm_search_does_not_retry_on_4xx():
    """4xx 客户端错误应立即抛 RuntimeError，不重试，并记录响应体。"""
    mock_response_4xx = MagicMock()
    mock_response_4xx.status_code = 400
    mock_response_4xx.text = '{"error":{"code":"1306","message":"网络搜索失败"}}'
    mock_response_4xx.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response_4xx)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        with patch("src.llm_search.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(RuntimeError, match="400 client error"):
                provider = GLMSearchProvider(
                    api_key="test", base_url="https://api.test.com", model="test"
                )
                await provider.search("2026-07-24")

    assert mock_client.post.await_count == 1  # 不重试
    mock_sleep.assert_not_awaited()


async def test_glm_search_retries_on_5xx_then_raises():
    """5xx 服务端错误应重试 3 次，仍失败抛 RuntimeError。"""
    mock_response_5xx = MagicMock()
    mock_response_5xx.status_code = 503
    mock_response_5xx.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503 error", request=MagicMock(), response=mock_response_5xx
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response_5xx)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        with patch("src.llm_search.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="GLM search failed after retries"):
                provider = GLMSearchProvider(
                    api_key="test", base_url="https://api.test.com", model="test"
                )
                await provider.search("2026-07-24")

    assert mock_client.post.await_count == 3


async def test_glm_search_structure_error_triggers_json_hint_retry():
    """响应 200 但 choices 结构异常时，应转 ValueError 触发 hint 重试，最终成功。"""
    mock_response_bad_struct = MagicMock()
    mock_response_bad_struct.status_code = 200
    mock_response_bad_struct.json.return_value = {"choices": []}  # 空 choices
    mock_response_bad_struct.raise_for_status = MagicMock()

    mock_response_good = MagicMock()
    mock_response_good.status_code = 200
    mock_response_good.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response_good.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_bad_struct, mock_response_good])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert result[0].name == "测试黑客松"
    assert mock_client.post.await_count == 2  # 第一次结构异常 + 第二次带 hint 成功


async def test_glm_search_empty_content_triggers_json_hint_retry():
    """响应 200 但 content 为空字符串时，应转 ValueError 触发 hint 重试。"""
    mock_response_empty = MagicMock()
    mock_response_empty.status_code = 200
    mock_response_empty.json.return_value = {
        "choices": [{"message": {"content": ""}}]  # 空 content
    }
    mock_response_empty.raise_for_status = MagicMock()

    mock_response_good = MagicMock()
    mock_response_good.status_code = 200
    mock_response_good.json.return_value = SAMPLE_LLM_RESPONSE
    mock_response_good.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_empty, mock_response_good])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.llm_search.httpx.AsyncClient", return_value=mock_client):
        provider = GLMSearchProvider(api_key="test", base_url="https://api.test.com", model="test")
        result = await provider.search("2026-07-24")

    assert len(result) == 1
    assert mock_client.post.await_count == 2
