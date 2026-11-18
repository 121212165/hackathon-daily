"""main.py 编排逻辑集成测试（Phase 1+2+3 版本）。

覆盖：
- 正常流程：chain 搜索 + 去重 + 渲染 + 发送 + 标记 → return 0
- 空结果：搜索返回 [] → skip → return 0
- 全部已见：get_unseen 返回 [] → 发空日邮件 + 不 mark → return 0（批次 5.6）
- chain 构建失败 → return 1
- 搜索异常 → return 1
- 发送异常 → return 1（不调 mark_pushed）
- 环境变量缺失 → return 1（provider key 至少一个；邮件三项硬必填）
- 只配 OPENAI_API_KEY 也能过预检（批次 0 / 0.2）
- 多收件人解析
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import main


def _set_env(monkeypatch, **overrides):
    """设置完整必填环境变量，可用 overrides 覆盖单个变量。

    默认清空全部 provider key（LLM/GLM/OPENAI），避免宿主环境残留 key 影响断言。
    """
    defaults = {
        "LLM_API_KEY": "llm-key",
        "GLM_API_KEY": "",
        "OPENAI_API_KEY": "",
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
                    with patch("src.main.render_email", return_value=("主题", "<html/>", "text")):
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


async def test_main_all_already_seen_sends_empty_digest(monkeypatch):
    """全部已见过 → 发「今日无新增」邮件 + 不调 mark_pushed（批次 5.6）。"""
    _set_env(monkeypatch)
    fake_hackathons = [_make_hackathon("A")]

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=fake_hackathons)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=[]):
            with patch(
                "src.main.render_empty_email",
                return_value=("空日主题", "<html/>", "text"),
            ) as mock_empty:
                with patch("src.main.count_pushed_last_7_days", return_value=7):
                    with patch("src.main.mark_pushed") as mock_mark:
                        with patch("src.main.ResendMailer") as MockMailer:
                            MockMailer.return_value.send = AsyncMock()
                            rc = await main()

    assert rc == 0
    mock_empty.assert_called_once()
    # 第二 / 三个参数是本周累计与 today
    assert mock_empty.call_args.args[1] == 7
    MockMailer.return_value.send.assert_awaited_once_with("空日主题", "<html/>", "text")
    mock_mark.assert_not_called()


async def test_main_empty_digest_top3_and_no_mark(monkeypatch):
    """空日邮件：TOP3 来自当日搜索结果（只读），且不写库。"""
    from datetime import timedelta

    from src.models import Hackathon, beijing_date

    def _h(name, days):
        return Hackathon(
            name=name,
            organizer="主办方",
            type_tag="AI",
            summary="简介",
            registration_deadline=(beijing_date() + timedelta(days=days)).isoformat(),
            start_date="待定",
            end_date="待定",
            location="线上",
            registration_url=f"https://example.com/{name}",
            detail_url=None,
        )

    _set_env(monkeypatch)
    found = [_h("晚", 30), _h("急", 1), _h("中", 6), _h("热", 2)]
    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=found)

    with patch("src.main.build_provider_chain", return_value=mock_chain):
        with patch("src.main.get_unseen", return_value=[]):
            with patch(
                "src.main.render_empty_email",
                return_value=("空日", "<html/>", "text"),
            ) as mock_empty:
                with patch("src.main.count_pushed_last_7_days", return_value=3):
                    with patch("src.main.mark_pushed") as mock_mark:
                        with patch("src.main.ResendMailer") as MockMailer:
                            MockMailer.return_value.send = AsyncMock()
                            rc = await main()

    assert rc == 0
    top3 = mock_empty.call_args.args[0]
    assert [h.name for h in top3] == ["急", "热"]  # ≤3 天，按 days_left 升序；中=6 天不入选
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
                    with patch("src.main.render_email", return_value=("主题", "<html/>", "text")):
                        rc = await main()

    assert rc == 1
    mock_mark.assert_not_called()


@pytest.mark.parametrize(
    "missing_env",
    ["LLM_API_KEY", "RESEND_API_KEY", "MAIL_FROM", "MAIL_TO"],
)
async def test_main_missing_env_returns_1(monkeypatch, missing_env):
    """任一必填 env 缺失 → return 1，不调用 LLM。

    注：LLM_API_KEY 缺失时 GLM_API_KEY / OPENAI_API_KEY 同样为空（_set_env 默认），
    即"一个 provider key 都没有"才判失败。
    """
    _set_env(monkeypatch, **{missing_env: ""})

    with patch("src.main.build_provider_chain") as mock_build:
        rc = await main()

    assert rc == 1
    mock_build.assert_not_called()


async def test_main_openai_key_only_passes_preflight(monkeypatch):
    """只配 OPENAI_API_KEY（LLM/GLM 为空）→ 预检通过，流程照常（0.2 验收）。"""
    _set_env(monkeypatch, LLM_API_KEY="", GLM_API_KEY="", OPENAI_API_KEY="oa-key")

    mock_chain = MagicMock()
    mock_chain.search = AsyncMock(return_value=[])

    with patch("src.main.build_provider_chain", return_value=mock_chain) as mock_build:
        with patch("src.main.ResendMailer") as MockMailer:
            MockMailer.return_value.send = AsyncMock()
            rc = await main()

    assert rc == 0
    mock_build.assert_called_once()


async def test_main_no_provider_key_returns_1(monkeypatch):
    """LLM/GLM/OPENAI 三个 key 全缺 → return 1，不构建链。"""
    _set_env(monkeypatch, LLM_API_KEY="", GLM_API_KEY="", OPENAI_API_KEY="")

    with patch("src.main.build_provider_chain") as mock_build:
        rc = await main()

    assert rc == 1
    mock_build.assert_not_called()


async def test_main_mail_config_still_hard_required(monkeypatch):
    """provider key 齐全但邮件配置缺失 → 仍 return 1（邮件三项未被放宽）。"""
    _set_env(
        monkeypatch,
        LLM_API_KEY="",
        GLM_API_KEY="",
        OPENAI_API_KEY="oa-key",
        RESEND_API_KEY="",
        MAIL_FROM="",
    )

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
                    with patch("src.main.render_email", return_value=("主题", "<html/>", "text")):
                        rc = await main()

    assert rc == 0
    # 验证收件人列表被正确解析并传入
    _, kwargs = MockMailer.call_args
    assert kwargs["to_email"] == ["a@x.com", "b@y.com", "c@z.com"]
