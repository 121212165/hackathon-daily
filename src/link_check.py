"""报名链接可达性校验：在发信前丢弃杜撰 / 失效链接，避免邮件里出现死链。

分层校验（成本从低到高）：
1. 静态判定 is_broken_link（占位域名 / 非法 scheme / 乱码 host）
2. DNS 解析：NXDOMAIN 直接判死（LLM 杜撰域名大半在这一层被拦下）
3. 已知域名停车 IP：判死（如 makerthon.org / codingcontest.org）
4. HTTP GET（跟随跳转）：404/410 或停车页特征 → 判死；
   网络超时 / 被拒等不确定错误 → 放行（fail-open），避免误杀真实赛事。

报名链接不可达但详情链接可达时，自动把详情链接提升为报名链接再保留该条。
无法校验的对象（如测试替身、非字符串 URL）原样保留，避免误伤。
"""

import asyncio
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .models import Hackathon, is_broken_link

logger = logging.getLogger(__name__)

# 实测命中的域名停车 / 售卖页 IP（Bodis、OVH parking 等）
_PARKING_IPS = frozenset(
    {
        "162.255.119.246",
        "50.85.64.152",
        "208.91.197.27",
    }
)

_PARKING_MARKERS = (
    "domain for sale",
    "buy this domain",
    "parked domain",
    "this domain is for sale",
    "域名停靠",
    "域名出售",
)

DNS_TIMEOUT = 3.0
HTTP_TIMEOUT = 5.0
CONCURRENCY = 8


@dataclass(frozen=True)
class Dropped:
    name: str
    url: str
    reason: str


def _normalized_url(url: str) -> str:
    """无 scheme 的裸域名补 https://，与 email_renderer.safe_url 保持一致。"""
    parsed = urlsplit(url)
    if parsed.scheme in ("http", "https"):
        return url
    first = parsed.path.split("/", 1)[0]
    if not url.startswith("/") and first[:1].isalnum() and "." in first:
        return f"https://{url}"
    return url


def _host(url: str) -> str:
    return (urlsplit(_normalized_url(url)).hostname or "").lower()


async def _resolve_host(host: str) -> set[str]:
    """解析域名，失败 / 超时返回空集合（由调用方判为 NXDOMAIN）。"""
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None), timeout=DNS_TIMEOUT
        )
        return {info[4][0] for info in infos}
    except (socket.gaierror, asyncio.TimeoutError, OSError):
        return set()


async def _reachable(
    url: str,
    dns_cache: dict[str, set[str]],
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[bool, str]:
    """返回 (是否可达, 原因)。"""
    if is_broken_link(url):
        return False, "static_broken"

    host = _host(url)
    if not host:
        return False, "no_host"

    if host not in dns_cache:
        async with sem:
            dns_cache[host] = await _resolve_host(host)
    ips = dns_cache[host]
    if not ips:
        return False, "dns_nxdomain"
    if ips & _PARKING_IPS:
        return False, "parking_ip"

    try:
        async with sem:
            resp = await client.get(_normalized_url(url))
        if resp.status_code in (404, 410):
            return False, f"http_{resp.status_code}"
        text = resp.text[:5000].lower()
        if any(marker in text for marker in _PARKING_MARKERS):
            return False, "parking_page"
    except (httpx.HTTPError, asyncio.TimeoutError):
        # 网络不确定时放行，宁可保留可疑链接也不误杀真实赛事
        logger.warning(f"[link-check] inconclusive for {url}, keeping (fail-open)")
    return True, "ok"


async def filter_reachable(
    hackathons: list[Hackathon],
) -> tuple[list[Hackathon], list[Dropped]]:
    """批量校验，返回 (保留列表, 被丢弃列表及原因)。"""
    kept: list[Hackathon] = []
    dropped: list[Dropped] = []
    dns_cache: dict[str, set[str]] = {}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; HackathonDaily/1.0)"},
    ) as client:
        for h in hackathons:
            reg = getattr(h, "registration_url", None)
            det = getattr(h, "detail_url", None)
            # 无法校验（测试替身 / 非字符串）→ 原样保留
            if not isinstance(reg, str) or not reg.strip():
                kept.append(h)
                continue

            ok, reason = await _reachable(reg, dns_cache, client, sem)
            if ok:
                kept.append(h)
                continue

            # 报名链接挂了但详情页可达 → 提升详情页作为报名链接
            if isinstance(det, str) and det.strip():
                ok_detail, _ = await _reachable(det, dns_cache, client, sem)
                if ok_detail:
                    h.registration_url = det
                    h.detail_url = None
                    kept.append(h)
                    continue

            dropped.append(Dropped(getattr(h, "name", "?"), reg, reason))

    return kept, dropped
