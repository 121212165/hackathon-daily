from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mailer import ResendMailer


async def test_resend_send_calls_api_correctly():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "email-123"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        mailer = ResendMailer(
            api_key="re_test",
            from_email="from@test.com",
            to_email="to@test.com",
        )
        await mailer.send("测试主题", "<html/>")

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args.kwargs
    assert call_kwargs["json"]["from"] == "from@test.com"
    assert call_kwargs["json"]["to"] == ["to@test.com"]
    assert call_kwargs["json"]["subject"] == "测试主题"
    assert call_kwargs["json"]["html"] == "<html/>"
    assert call_kwargs["headers"]["Authorization"] == "Bearer re_test"


async def test_resend_send_retries_on_5xx_then_succeeds():
    """5xx 服务端错误应重试，第二次成功则整体成功。"""
    mock_response_fail = MagicMock()
    mock_response_fail.status_code = 503
    mock_response_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503 error",
        request=MagicMock(),
        response=mock_response_fail,
    )

    mock_response_ok = MagicMock()
    mock_response_ok.status_code = 200
    mock_response_ok.json.return_value = {"id": "email-456"}
    mock_response_ok.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[mock_response_fail, mock_response_ok])
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        with patch("src.mailer.asyncio.sleep", new=AsyncMock()):
            mailer = ResendMailer(api_key="re_test", from_email="a@b.com", to_email="c@d.com")
            await mailer.send("subject", "<html/>")

    assert mock_client.post.await_count == 2


async def test_resend_send_does_not_retry_on_4xx():
    """4xx 客户端错误应立即抛 RuntimeError，不重试。"""
    mock_response_4xx = MagicMock()
    mock_response_4xx.status_code = 422
    mock_response_4xx.text = '{"error":"invalid email"}'
    mock_response_4xx.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response_4xx)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        with patch("src.mailer.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            mailer = ResendMailer(api_key="re_test", from_email="a@b.com", to_email="c@d.com")
            with pytest.raises(RuntimeError, match="422 client error"):
                await mailer.send("subject", "<html/>")

    assert mock_client.post.await_count == 1  # 不重试
    mock_sleep.assert_not_awaited()


async def test_resend_send_retries_on_network_error_then_raises():
    """网络错误重试 2 次（共 3 次尝试），仍失败抛 RuntimeError。"""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("src.mailer.httpx.AsyncClient", return_value=mock_client):
        with patch("src.mailer.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="Resend send failed after retries"):
                mailer = ResendMailer(api_key="re_test", from_email="a@b.com", to_email="c@d.com")
                await mailer.send("subject", "<html/>")

    assert mock_client.post.await_count == 3
