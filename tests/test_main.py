"""main.py 编排逻辑集成测试（Phase 1+2+3 版本）。

覆盖：
- 正常流程：chain 搜索 + 去重 + 渲染 + 发送 + 标记 → return 0
- 空结果：搜索返回 [] → skip → return 0
- 全部已见：get_unseen 返回 [] → skip → return 0
- chain 构建失败 → return 1
- 搜索异常 → return 1
- 发送异常 → return 1（不调 mark_pushed）
- 环境变量缺失 → return 1
- 多收件人解析
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import main


def _set_env(monkeypatch, **overrides):
    """设置完整必填环境变量，可用 overrides 覆盖单个变量。"""
    defaults = {
        "LLM_API_KEY": "llm-key",
        "RESEND_API_KEY": "re-key",
        "MAIL_FROM": "from@test.com",
        "MAIL_TO": "to@test.com",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


def _make_hackathon(name="测试黑客松"):
    """构造一个模拟 Hackathon。"""
    h = MagicMock()
    h.name = name
    return h


async def test_main_happy_path(monkeypatch, tmp_path):
    """正常流程：搜索 + 去重 + 发送 + 标记 → return 0。"""
    _set_env(monkeypatch)
    fake_hackathons = [_make_hackathon("A"), _make_hackathon("B")]

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=fake_hackathons)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=fake_hackathons):
            with patch("src.main.mark_pushed") as mock_mark:
                with patch("src.main.ResendMailer") as MockMailer:
                    MockMailer.return_value.send = AsyncMock(return_value=None)
                    with patch("src.main.render_email", return_value=("主题", "<html/>")):
                        rc = await main()

    assert rc == 0
    mock_chain.search.assert_awaited_once()
    MockMailer.return_value.send.assert_awaited_once()
    mock_mark.assert_called_once()


async def test_main_empty_search_result(monkeypatch):
    """搜索返回空列表 → skip → return 0。"""
    _set_env(monkeypatch)

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=[])

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen") as mock_unseen:
            with patch("src.main.ResendMailer") as MockMailer:
                MockMailer.return_value.send = AsyncMock()
                rc = await main()

    assert rc == 0
    mock_unseen.assert_not_called()
    MockMailer.return_value.send.assert_not_awaited()


async def test_main_all_already_seen(monkeypatch):
    """全部已见过 → get_unseen 返回 [] → skip → return 0。"""
    _set_env(monkeypatch)
    fake_hackathons = [_make_hackathon("A")]

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=fake_hackathons)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=[]):
            with patch("src.main.mark_pushed") as mock_mark:
                with patch("src.main.ResendMailer") as MockMailer:
                    MockMailer.return_value.send = AsyncMock()
                    rc = await main()

    assert rc == 0
    MockMailer.return_value.send.assert_not_awaited()
    mock_mark.assert_not_called()


async def test_main_chain_build_failure(monkeypatch):
    """chain 构建失败 → return 1。"""
    _set_env(monkeypatch)

    with patch("src.main.build_provider_chain", side_effect=ValueError("no provider")):
        rc = await main()

    assert rc == 1


async def test_main_search_exception(monkeypatch):
    """搜索抛异常 → return 1，不调用 mailer。"""
    _set_env(monkeypatch)

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(side_effect=RuntimeError("LLM down"))

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock()
            rc = await main()

    assert rc == 1
    MockMailer.return_value.send.assert_not_awaited()


async def test_main_send_exception_no_mark(monkeypatch):
    """发送抛异常 → return 1，且不调 mark_pushed（下次重试）。"""
    _set_env(monkeypatch)
    fake_hackathons = [_make_hackathon("A")]

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=fake_hackathons)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=fake_hackathons):
            with patch("src.main.mark_pushed") as mock_mark:
                with patch("src.main.ResendMailer") as MockMailer:
                    MockMailer.return_value.send = AsyncMock(
                        side_effect=RuntimeError("Resend down")
                    )
                    with patch("src.main.render_email", return_value=("主题", "<html/>")):
                        rc = await main()

    assert rc == 1
    mock_mark.assert_not_called()


@pytest.mark.parametrize(
    "missing_env",
    ["LLM_API_KEY", "RESEND_API_KEY", "MAIL_FROM", "MAIL_TO"],
)
async def test_main_missing_env_returns_1(monkeypatch, missing_env):
    """任一必填 env 缺失 → return 1，不调用 LLM。"""
    _set_env(monkeypatch, **{missing_env: ""})

    with patch("src.main.build_provider_chain") as mock_build:
        rc = await main()

    assert rc == 1
    mock_build.assert_not_called()


async def test_main_multiple_recipients(monkeypatch):
    """多收件人：MAIL_TO 逗号分隔 → 传 list 给 ResendMailer。"""
    _set_env(monkeypatch, MAIL_TO="a@x.com,b@y.com, c@z.com")
    fake_hackathons = [_make_hackathon("A")]

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=fake_hackathons)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=fake_hackathons):
            with patch("src.main.mark_pushed"):
                with patch("src.main.ResendMailer") as MockMailer:
                    MockMailer.return_value.send = AsyncMock(return_value=None)
                    with patch("src.main.render_email", return_value=("主题", "<html/>")):
                        rc = await main()

    assert rc == 0
    # 验证收件人列表被正确解析并传入
    _, kwargs = MockMailer.call_args
    assert kwargs["to_email"] == ["a@x.com", "b@y.com", "c@z.com"]
