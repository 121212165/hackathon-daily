"""Devpost 源：discover 页解析。

实测 devpost.com/hackathons 对无头请求返回 403（反爬）；按计划约定
「反爬/结构变化 → 记 warning 跳过，不阻塞其它源」。
若页面能取到，则优先解析 JSON-LD，其次回退到赛事卡片链接。
"""

import html as html_lib
import json
import logging
import os
import re

import httpx

from ..models import Hackathon
from .base import SearchProvider

logger = logging.getLogger(__name__)

DEVPOST_URL = "https://devpost.com/hackathons"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_HACK_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'](https://devpost\.com/hackathons/[^"\'#]+)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: object) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", str(raw or ""))).strip()


def _walk_dicts(obj: object):
    if isinstance(obj, list):
        for item in obj:
            yield from _walk_dicts(item)
    elif isinstance(obj, dict):
        yield obj
        for value in obj.values():
            if isinstance(value, (dict, list)):
                yield from _walk_dicts(value)


def _to_dict(item: dict) -> dict | None:
    name = _clean_text(item.get("name") or item.get("title"))
    url = item.get("url") or item.get("registration_url")
    if not name or not isinstance(url, str) or "devpost.com/hackathons/" not in url:
        return None
    return {
        "name": name[:200],
        "organizer": _clean_text(item.get("organizer")) or "Devpost",
        "type_tag": _clean_text(item.get("type_tag")) or "综合",
        "summary": _clean_text(item.get("description") or item.get("summary"))[:300],
        "registration_deadline": _clean_text(item.get("registration_deadline")) or "待定",
        "start_date": _clean_text(item.get("startDate"))[:10] or "待定",
        "end_date": _clean_text(item.get("endDate"))[:10] or "待定",
        "location": _clean_text(item.get("location")) or "线上",
        "registration_url": url,
        "detail_url": url,
    }


class DevpostProvider(SearchProvider):
    """无需 key；抓取失败或结构变化返回空列表并记 warning。"""

    def __init__(self, url: str = DEVPOST_URL, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "devpost"

    @classmethod
    def from_env(cls) -> "DevpostProvider | None":
        if os.environ.get("DEVPOST_ENABLED", "1").strip().lower() in ("0", "false", "no"):
            logger.warning("Devpost provider: disabled by DEVPOST_ENABLED, skipping")
            return None
        return cls(url=os.environ.get("DEVPOST_URL", DEVPOST_URL))

    def _parse(self, page: str) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()

        for block in _JSONLD_RE.findall(page):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            for candidate in _walk_dicts(data):
                parsed = _to_dict(candidate)
                if parsed and parsed["registration_url"] not in seen:
                    seen.add(parsed["registration_url"])
                    items.append(parsed)

        if not items:
            for url, anchor in _HACK_LINK_RE.findall(page):
                parsed = _to_dict({"name": anchor, "url": url.split("?", 1)[0]})
                if parsed and parsed["registration_url"] not in seen:
                    seen.add(parsed["registration_url"])
                    items.append(parsed)
        return items

    async def search(self, today: str) -> list[Hackathon]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(self.url, headers=_BROWSER_HEADERS)
                response.raise_for_status()
                items = self._parse(response.text)
        except Exception as e:
            logger.warning(f"Devpost fetch failed, skipping: {e}")
            return []

        if not items:
            logger.warning("Devpost returned no parseable events (anti-bot/structure change)")
        result: list[Hackathon] = []
        for item in items:
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"Devpost: skip invalid entry: {e}")
        return result
