"""Serper (Google SERP) 源：只做召回，结构化交给一次便宜 LLM 调用。

POST https://google.serper.dev/search  header X-API-KEY  body {q, num}
返回 organic[{title, link, snippet}] → structure_search_results() → extract_json。
无 SERPER_API_KEY / 调用失败 → warning + 空列表。
"""

import logging
import os

import httpx

from ..models import Hackathon
from ._common import structure_search_results
from .base import SearchProvider

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
DEFAULT_QUERY = "2026 线上黑客松 报名 中国大陆 AI 数据 全栈"


class SerperProvider(SearchProvider):
    def __init__(self, api_key: str, api_url: str = SERPER_URL, query: str = DEFAULT_QUERY):
        self.api_key = api_key
        self.api_url = api_url
        self.query = query

    @property
    def name(self) -> str:
        return "serper"

    @classmethod
    def from_env(cls) -> "SerperProvider | None":
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            logger.warning("Serper provider: no SERPER_API_KEY, will be skipped")
            return None
        return cls(
            api_key=api_key,
            api_url=os.environ.get("SERPER_API_URL", SERPER_URL),
            query=os.environ.get("SERPER_QUERY", DEFAULT_QUERY),
        )

    async def search(self, today: str) -> list[Hackathon]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    self.api_url,
                    headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                    json={"q": self.query, "num": 10},
                )
                response.raise_for_status()
                data = response.json()
            organic = data.get("organic") if isinstance(data, dict) else None
            if not isinstance(organic, list):
                logger.warning("Serper response has no organic array, skipping")
                return []
            snippets = [
                {"title": item.get("title", ""), "link": item.get("link", ""),
                 "snippet": item.get("snippet", "")}
                for item in organic
                if isinstance(item, dict) and item.get("link")
            ]
        except Exception as e:
            logger.warning(f"Serper search failed, skipping: {e}")
            return []

        structured = await structure_search_results(snippets, today)
        result: list[Hackathon] = []
        for item in structured:
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"Serper: skip invalid entry: {e}")
        return result
