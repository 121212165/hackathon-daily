"""报名链接可达性校验 + SERP URL 证据绑定的单元测试（不发真实网络请求）。"""

import httpx
import pytest

from src.link_check import filter_reachable
from src.models import Hackathon, is_broken_link
from src.providers._common import ground_urls


class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Client:
    """可注入的假 HTTP 客户端；get_result 可为 _Resp 或异常实例。"""

    def __init__(self, get_result=None):
        self.get_result = get_result or _Resp()
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        self.calls.append(url)
        if isinstance(self.get_result, BaseException):
            raise self.get_result
        return self.get_result


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """默认假 HTTP 客户端：所有测试都不发真实网络请求。"""
    client = _Client()
    monkeypatch.setattr("src.link_check.httpx.AsyncClient", lambda **kwargs: client)
    return client


def _hackathon(reg, detail=None, name="测试赛事"):
    return Hackathon.from_dict(
        {"name": name, "registration_url": reg, "detail_url": detail}
    )


def _resolver(map_: dict[str, set[str]]):
    async def resolve(host):
        return map_.get(host, set())

    return resolve


async def test_nxdomain_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host", _resolver({"aicontest.org": set()})
    )
    kept, dropped = await filter_reachable([_hackathon("https://aicontest.org/register")])
    assert kept == []
    assert dropped[0].reason == "dns_nxdomain"


async def test_parking_ip_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"makerthon.org": {"162.255.119.246"}}),
    )
    kept, dropped = await filter_reachable([_hackathon("https://makerthon.org/register")])
    assert kept == []
    assert dropped[0].reason == "parking_ip"


async def test_http_404_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"contest.example.net": {"1.2.3.4"}}),
    )
    monkeypatch.setattr(
        "src.link_check.httpx.AsyncClient",
        lambda **kwargs: _Client(_Resp(404)),
    )
    kept, dropped = await filter_reachable(
        [_hackathon("https://contest.example.net/register")]
    )
    assert kept == []
    assert dropped[0].reason == "http_404"


async def test_parking_page_content_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"contest.example.net": {"1.2.3.4"}}),
    )
    monkeypatch.setattr(
        "src.link_check.httpx.AsyncClient",
        lambda **kwargs: _Client(_Resp(200, "This domain is for sale - buy this domain")),
    )
    kept, dropped = await filter_reachable(
        [_hackathon("https://contest.example.net/register")]
    )
    assert kept == []
    assert dropped[0].reason == "parking_page"


async def test_bot_challenge_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"contest.example.net": {"1.2.3.4"}}),
    )
    monkeypatch.setattr(
        "src.link_check.httpx.AsyncClient",
        lambda **kwargs: _Client(_Resp(403, "Just a moment...")),
    )
    kept, dropped = await filter_reachable(
        [_hackathon("https://contest.example.net/register")]
    )
    assert kept == []
    assert dropped[0].reason == "bot_challenge"


async def test_ssl_error_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"real.example.net": {"5.6.7.8"}}),
    )
    monkeypatch.setattr(
        "src.link_check.httpx.AsyncClient",
        lambda **kwargs: _Client(
            httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        ),
    )
    kept, dropped = await filter_reachable(
        [_hackathon("https://real.example.net/register")]
    )
    assert kept == []
    assert dropped[0].reason == "ssl_error"


def test_example_numbered_domains_are_placeholders():
    """dry-run 漏网之鱼：example2.com / www.example3.com 必须判为占位域名。"""
    for url in (
        "http://www.example2.com/registration",
        "https://example3.org/register",
        "https://test1.com/signup",
    ):
        assert is_broken_link(url) is True, url


async def test_registration_dead_detail_alive_promoted(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"aicontest.org": set(), "real.example.net": {"5.6.7.8"}}),
    )
    h = _hackathon("https://aicontest.org/register", "https://real.example.net/event")
    kept, dropped = await filter_reachable([h])
    assert dropped == []
    assert len(kept) == 1
    assert kept[0].registration_url == "https://real.example.net/event"
    assert kept[0].detail_url is None


async def test_placeholder_reg_falls_back_to_detail(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host", _resolver({"real.example.net": {"5.6.7.8"}})
    )
    h = _hackathon("https://example.com/register", "https://real.example.net/event")
    kept, dropped = await filter_reachable([h])
    assert dropped == []
    assert kept[0].registration_url == "https://real.example.net/event"


async def test_uninspectable_object_kept():
    """测试替身 / 非字符串 URL 无法校验 → 原样保留。"""
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.name = "替身"
    kept, dropped = await filter_reachable([fake])
    assert kept == [fake]
    assert dropped == []


async def test_network_error_fail_open(monkeypatch):
    monkeypatch.setattr(
        "src.link_check._resolve_host",
        _resolver({"real.example.net": {"5.6.7.8"}}),
    )
    monkeypatch.setattr(
        "src.link_check.httpx.AsyncClient",
        lambda **kwargs: _Client(httpx.TimeoutException("timeout")),
    )
    kept, dropped = await filter_reachable(
        [_hackathon("https://real.example.net/register")]
    )
    assert len(kept) == 1
    assert dropped == []


def test_ground_urls_drops_hallucinated_url():
    evidence = '[{"link": "https://devpost.com/hackathons/real-event"}]'
    items = [
        {"name": "真赛事", "registration_url": "https://devpost.com/hackathons/real-event"},
        {"name": "假赛事", "registration_url": "https://aicontest.org/register"},
    ]
    result = ground_urls(items, evidence)
    assert len(result) == 1
    assert result[0]["name"] == "真赛事"


def test_ground_urls_drops_ungrounded_detail_only():
    evidence = '[{"link": "https://devpost.com/hackathons/real-event"}]'
    items = [
        {
            "name": "真赛事",
            "registration_url": "https://devpost.com/hackathons/real-event",
            "detail_url": "https://fake-detail.org/page",
        }
    ]
    result = ground_urls(items, evidence)
    assert len(result) == 1
    assert result[0]["detail_url"] is None
