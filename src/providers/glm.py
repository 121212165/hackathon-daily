"""GLM (智谱) Provider：通过 GLM 联网搜索 API 获取黑客松列表。

使用智谱"Web Search in Chat"能力：glm-4-flash 模型 + web_search 工具。
"""

import logging
import os

from ..models import Hackathon
from ._common import JSON_HINT, SYSTEM_PROMPT, call_chat_api, parse_hackathons
from .base import LLMProvider

logger = logging.getLogger(__name__)


class GLMProvider(LLMProvider):
    """智谱 GLM 搜索 Provider。

    错误处理：
    - HTTP/网络错误：retry 2 次（指数退避 1s, 4s），仍失败 → 抛 RuntimeError
    - JSON 解析错误：retry 1 次带 hint，仍失败 → 返回空列表
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
        """从环境变量构建。无 API key 时返回 None（被 chain 跳过）。"""
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
        user_msg = f"今天是 {today}。请搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松。"
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
