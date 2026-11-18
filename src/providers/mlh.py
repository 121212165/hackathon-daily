"""MLH 源：从赛事日历页的 Inertia JSON blob 解析 upcomingEvents。

可达性探测（2026-11-18）：mlh.io/events 可正常访问，页面内
<script data-page="app" type="application/json"> 的 props.upcomingEvents
含 name / startsAt / endsAt / websiteUrl / location 等字段。
结构变化 → 记 warning 跳过，不阻塞其它源。
"""

import json
import logging
import os
import re

import httpx

from ..models import Hackathon
from .base import SearchProvider

logger = logging.getLogger(__name__)

MLH_URL = "https://mlh.io/events"
_DATA_RE = re.compile(
    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', re.I | re.S
)


def _to_dict(event: dict) -> dict | None:
    name = event.get("name")
    if not name:
        return None
    event_path = event.get("url")
    detail_url = f"https://www.mlh.com{event_path}" if event_path else ""
    registration_url = event.get("websiteUrl") or detail_url
    if not registration_url:
        return None
    focus = ((event.get("customFields") or {}).get("hackathon_focus") or [])
    return {
        "name": name,
        "organizer": event.get("organizationName") or "MLH",
        "type_tag": focus[0] if focus else (event.get("formatLabel") or "综合"),
        "summary": " ".join(
            part for part in (event.get("dateRange"), event.get("location")) if part
        ),
        "registration_deadline": "待定",
        "start_date": str(event.get("startsAt") or "待定")[:10],
        "end_date": str(event.get("endsAt") or "待定")[:10],
        "location": event.get("location") or "线上",
        "registration_url": registration_url,
        "detail_url": detail_url or registration_url,
    }


class MLHProvider(SearchProvider):
    """无需 key；解析失败返回空列表并记 warning。"""

    def __init__(self, url: str = MLH_URL, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "mlh"

    @classmethod
    def from_env(cls) -> "MLHProvider | None":
        if os.environ.get("MLH_ENABLED", "1").strip().lower() in ("0", "false", "no"):
            logger.warning("MLH provider: disabled by MLH_ENABLED, skipping")
            return None
        return cls(url=os.environ.get("MLH_URL", MLH_URL))

    def _parse(self, page: str) -> list[dict]:
        for block in _DATA_RE.findall(page):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            events = (data.get("props") or {}).get("upcomingEvents")
            if not isinstance(events, list):
                continue
            parsed = [item for event in events if isinstance(event, dict)
                      if (item := _to_dict(event))]
            if parsed:
                return parsed
        return []

    async def search(self, today: str) -> list[Hackathon]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(self.url)
                response.raise_for_status()
                items = self._parse(response.text)
        except Exception as e:
            logger.warning(f"MLH fetch failed, skipping: {e}")
            return []

        if not items:
            logger.warning("MLH returned no parseable events (structure change)")
        result: list[Hackathon] = []
        for item in items:
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"MLH: skip invalid entry: {e}")
        return result
