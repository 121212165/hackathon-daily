"""Tavily 源：搜索 API 拿链接+正文，一次便宜 LLM 调用结构化。

POST https://api.tavily.com/search  body {api_key, query, max_results, search_depth}
无 TAVILY_API_KEY / 调用失败 → warning + 空列表。
"""

import logging
import os

import httpx

from ..models import Hackathon
from ._common import structure_search_results
from .base import SearchProvider

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_QUERY = "2026 线上黑客松 报名 中国大陆 AI 数据 全栈"


class TavilyProvider(SearchProvider):
    def __init__(self, api_key: str, api_url: str = TAVILY_URL, query: str = DEFAULT_QUERY):
        self.api_key = api_key
        self.api_url = api_url
        self.query = query

    @property
    def name(self) -> str:
        return "tavily"

    @classmethod
    def from_env(cls) -> "TavilyProvider | None":
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logger.warning("Tavily provider: no TAVILY_API_KEY, will be skipped")
            return None
        return cls(
            api_key=api_key,
            api_url=os.environ.get("TAVILY_API_URL", TAVILY_URL),
            query=os.environ.get("TAVILY_QUERY", DEFAULT_QUERY),
        )

    async def search(self, today: str) -> list[Hackathon]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    self.api_url,
                    json={
                        "api_key": self.api_key,
                        "query": self.query,
                        "max_results": 10,
                        "search_depth": "basic",
                    },
                )
                response.raise_for_status()
                data = response.json()
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                logger.warning("Tavily response has no results array, skipping")
                return []
            snippets = [
                {"title": item.get("title", ""), "url": item.get("url", ""),
                 "content": item.get("content", "")}
                for item in results
                if isinstance(item, dict) and item.get("url")
            ]
        except Exception as e:
            logger.warning(f"Tavily search failed, skipping: {e}")
            return []

        structured = await structure_search_results(snippets, today)
        result: list[Hackathon] = []
        for item in structured:
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"Tavily: skip invalid entry: {e}")
        return result
