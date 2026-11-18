"""clist.rocks 源：官方 JSON API（需 CLIST_USERNAME / CLIST_API_KEY）。

未配置 key → from_env() 返回 None，链上跳过；请求失败/结构变化 → warning + 空列表。
"""

import logging
import os

import httpx

from ..models import Hackathon
from .base import SearchProvider

logger = logging.getLogger(__name__)

CLIST_API_URL = "https://clist.by/api/v4/contest/"


def _to_dict(item: dict) -> dict | None:
    name = item.get("event") or item.get("name")
    if not name:
        return None
    url = item.get("url") or item.get("href")
    if not url and item.get("id"):
        url = f"https://clist.by/contest/{item['id']}/"
    if not url:
        return None
    return {
        "name": str(name),
        "organizer": str(item.get("host") or "clist"),
        "type_tag": str(item.get("type") or "竞赛"),
        "summary": str(item.get("description") or "")[:300],
        "registration_deadline": "待定",
        "start_date": str(item.get("start") or "待定")[:10],
        "end_date": str(item.get("end") or "待定")[:10],
        "location": str(item.get("location") or "线上"),
        "registration_url": url,
        "detail_url": url,
    }


class ClistProvider(SearchProvider):
    def __init__(
        self,
        username: str,
        api_key: str,
        api_url: str = CLIST_API_URL,
        timeout: float = 15.0,
    ):
        self.username = username
        self.api_key = api_key
        self.api_url = api_url
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "clist"

    @classmethod
    def from_env(cls) -> "ClistProvider | None":
        username = os.environ.get("CLIST_USERNAME")
        api_key = os.environ.get("CLIST_API_KEY")
        if not username or not api_key:
            logger.warning("clist provider: no CLIST_USERNAME/CLIST_API_KEY, will be skipped")
            return None
        return cls(
            username=username,
            api_key=api_key,
            api_url=os.environ.get("CLIST_API_URL", CLIST_API_URL),
        )

    async def search(self, today: str) -> list[Hackathon]:
        params = {
            "username": self.username,
            "api_key": self.api_key,
            "limit": 50,
            "order_by": "start",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.api_url, params=params)
                response.raise_for_status()
                data = response.json()
            objects = data.get("objects") if isinstance(data, dict) else None
            if not isinstance(objects, list):
                logger.warning("clist response has no objects array, skipping")
                return []
        except Exception as e:
            logger.warning(f"clist fetch failed, skipping: {e}")
            return []

        result: list[Hackathon] = []
        for item in objects:
            if not isinstance(item, dict):
                continue
            parsed = _to_dict(item)
            if parsed is None:
                continue
            try:
                result.append(Hackathon.from_dict(parsed))
            except ValueError as e:
                logger.warning(f"clist: skip invalid entry: {e}")
        return result
