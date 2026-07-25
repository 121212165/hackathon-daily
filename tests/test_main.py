"""main.py 编排逻辑集成测试。

mock GLMSearchProvider 和 ResendMailer，覆盖：
- 正常流程：搜索成功 + 发送成功 → return 0
- 空结果：搜索返回 [] → 不调用 mailer，return 0
- 搜索异常 → return 1
- 发送异常 → return 1
- 环境变量缺失（任一必填）→ return 1，不调用 LLM 也不调用 mailer
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import main


def _set_env(monkeypatch, **overrides):
    """设置完整必填环境变量，可用 overrides 覆盖单个变量。"""
    defaults = {
        "LLM_API_KEY": "llm-key",
        "LLM_BASE_URL": "https://api.test.com",
        "LLM_MODEL": "test-model",
        "RESEND_API_KEY": "re-key",
        "MAIL_FROM": "from@test.com",
        "MAIL_TO": "to@test.com",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


async def test_main_happy_path(monkeypatch):
    """正常流程：搜索成功 + 邮件发送成功 → return 0。"""
    _set_env(monkeypatch)
    fake_hackathons = [MagicMock()]
    fake_hackathons[0].name = "测试"

    with patch("src.main.GLMSearchProvider") as MockProvider:
        MockProvider.return_value.search = AsyncMock(return_value=fake_hackathons)
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock(return_value=None)
            with patch("src.main.render_email", return_value=("主题", "<html/>")):
                rc = await main()

    assert rc == 0
    MockProvider.return_value.search.assert_awaited_once()
    MockMailer.return_value.send.assert_awaited_once()


async def test_main_empty_result_skips_send(monkeypatch):
    """搜索返回空列表 → 不调用 mailer，return 0。"""
    _set_env(monkeypatch)

    with patch("src.main.GLMSearchProvider") as MockProvider:
        MockProvider.return_value.search = AsyncMock(return_value=[])
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock(return_value=None)
            rc = await main()

    assert rc == 0
    MockProvider.return_value.search.assert_awaited_once()
    MockMailer.return_value.send.assert_not_awaited()


async def test_main_search_exception_returns_1(monkeypatch):
    """搜索抛异常 → return 1，不调用 mailer。"""
    _set_env(monkeypatch)

    with patch("src.main.GLMSearchProvider") as MockProvider:
        MockProvider.return_value.search = AsyncMock(side_effect=RuntimeError("LLM down"))
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock(return_value=None)
            rc = await main()

    assert rc == 1
    MockProvider.return_value.search.assert_awaited_once()
    MockMailer.return_value.send.assert_not_awaited()


async def test_main_send_exception_returns_1(monkeypatch):
    """邮件发送抛异常 → return 1。"""
    _set_env(monkeypatch)
    fake_hackathons = [MagicMock()]

    with patch("src.main.GLMSearchProvider") as MockProvider:
        MockProvider.return_value.search = AsyncMock(return_value=fake_hackathons)
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock(side_effect=RuntimeError("Resend down"))
            with patch("src.main.render_email", return_value=("主题", "<html/>")):
                rc = await main()

    assert rc == 1
    MockProvider.return_value.search.assert_awaited_once()
    MockMailer.return_value.send.assert_awaited_once()


@pytest.mark.parametrize(
    "missing_env",
    ["LLM_API_KEY", "RESEND_API_KEY", "MAIL_FROM", "MAIL_TO"],
)
async def test_main_missing_env_returns_1_without_llm_call(monkeypatch, missing_env):
    """任一必填 env 缺失 → return 1，且不调用 LLM（避免浪费计费）。"""
    _set_env(monkeypatch, **{missing_env: ""})

    with patch("src.main.GLMSearchProvider") as MockProvider:
        MockProvider.return_value.search = AsyncMock(return_value=[])
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock(return_value=None)
            rc = await main()

    assert rc == 1
    # 关键：env 缺失时不应调用 LLM provider，避免浪费 API 计费
    MockProvider.return_value.search.assert_not_awaited()
    MockMailer.return_value.send.assert_not_awaited()
