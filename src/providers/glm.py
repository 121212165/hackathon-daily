"""GLM (智谱) Provider：通过 GLM 联网搜索 API 获取黑客松列表。

使用智谱"Web Search in Chat"能力：glm-4-search + web_search 工具。
批次 1：按 QUERIES 扇出多查询并发搜索，LLM_FANOUT 控制查询数（1 = 退回现状）。
"""

import asyncio
import logging
import os

from ..models import Hackathon
from ..store import normalize_url, title_hash
from ._common import JSON_HINT, SYSTEM_PROMPT, call_chat_api, parse_hackathons
from .base import LLMProvider

logger = logging.getLogger(__name__)

QUERIES = [
    "AI / 大模型 / AIGC 类线上黑客松",
    "数据 / 机器学习 / 数据分析类",
    "全栈 / Web / 小程序类",
    "硬件 / 创客 / 物联网类（含线上赛道）",
    "面向在校学生的线上编程竞赛",
]


def fanout_size() -> int:
    """LLM_FANOUT = 本次执行的查询条数（默认 4，1 即原来的单查询）。"""
    raw = os.environ.get("LLM_FANOUT", "4")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 4
    return max(1, min(value, len(QUERIES)))


class GLMProvider(LLMProvider):
    """智谱 GLM 搜索 Provider。

    错误处理：
    - 单查询失败/空结果：warning，不影响其余查询；全部查询失败才抛 RuntimeError
    - JSON 解析错误：带 hint 重试一次，仍失败则该查询返回空列表
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/",
        model: str = "glm-4-search",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "glm"

    @classmethod
    def from_env(cls) -> "GLMProvider | None":
        """无 API key 时返回 None（被链跳过）。"""
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GLM_API_KEY")
        if not api_key:
            logger.warning("GLM provider: no LLM_API_KEY/GLM_API_KEY, will be skipped")
            return None
        return cls(
            api_key=api_key,
            base_url=os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
            model=os.environ.get("LLM_MODEL", "glm-4-search"),
        )

    async def search(self, today: str) -> list[Hackathon]:
        queries = QUERIES[: fanout_size()]
        outcomes = await asyncio.gather(
            *(self._search_one(query, today) for query in queries),
            return_exceptions=True,
        )

        merged: list[Hackathon] = []
        seen: set[str] = set()
        errors: list[str] = []
        for query, outcome in zip(queries, outcomes):
            if isinstance(outcome, BaseException):
                message = f"{query}: {outcome}"
                logger.warning(f"GLM query failed: {message}")
                errors.append(message)
                continue
            for hackathon in outcome:
                norm = normalize_url(hackathon.registration_url)
                key = f"url:{norm}" if norm else f"title:{title_hash(hackathon)}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(hackathon)

        if len(errors) == len(queries):
            raise RuntimeError("All GLM queries failed: " + "; ".join(errors))
        return merged

    async def _search_one(self, query: str, today: str) -> list[Hackathon]:
        """单条查询：JSON 失败带 hint 重试一次，仍失败返回空列表。"""
        user_msg = (
            f"今天是 {today}。请搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松。"
            f"本轮重点方向：{query}。"
        )
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        json_hint_used = False
        for _ in range(2):
            messages = list(base_messages)
            if json_hint_used:
                messages.append({"role": "user", "content": JSON_HINT})
            try:
                content = await self._call_api(messages)
                return parse_hackathons(content)
            except ValueError as e:
                if not json_hint_used:
                    json_hint_used = True
                    logger.warning(f"JSON parse failed, will retry with hint: {e}")
                    continue
                logger.error(f"JSON parse failed after hint retry, skipping: {e}")
                return []
        return []

    async def _call_api(self, messages: list[dict]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # 智谱"Web Search in Chat"：通过 tools 启用 web_search 工具
            "tools": [
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": True,
                        "search_engine": "search_std",
                        "search_result": True,
                    },
                }
            ],
        }
        return await call_chat_api(url, headers, payload, self.timeout)
