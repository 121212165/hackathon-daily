from unittest.mock import AsyncMock, MagicMock, patch

from src.mailer import ResendMailer


async def test_resend_send_calls_api_correctly():
    mock_response = MagicMock()
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


async def test_resend_send_retries_on_failure():
    mock_response_fail = MagicMock()
    mock_response_fail.raise_for_status.side_effect = Exception("500 error")
    mock_response_ok = MagicMock()
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
