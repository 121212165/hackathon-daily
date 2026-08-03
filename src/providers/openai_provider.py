"""OpenAI 兼容 Provider：支持 DeepSeek/Kimi/通义等 OpenAI 兼容 API。

作为 GLM 的 fallback：GLM 失败时自动切换。
需配合支持 web search 的模型或带联网能力的模型使用。
"""

import logging
import os

from ..models import Hackathon
from ._common import JSON_HINT, SYSTEM_PROMPT, call_chat_api, parse_hackathons
from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容 API Provider（可接 DeepSeek/Kimi 等）。

    使用标准 chat/completions 接口。若模型支持 web search
    （如 DeepSeek 未内置联网，需配合搜索工具），通过额外参数启用。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "openai"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider | None":
        """从环境变量构建。无 API key 时返回 None（被 chain 跳过）。"""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OpenAI provider: no OPENAI_API_KEY, will be skipped")
            return None
        return cls(
            api_key=api_key,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.environ.get("OPENAI_MODEL", "deepseek-chat"),
        )

    async def search(self, today: str) -> list[Hackathon]:
        user_msg = (
            f"今天是 {today}。请搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松。"
            "如果你有联网搜索能力，请使用它获取最新信息。"
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
                    logger.warning(f"OpenAI JSON parse failed, will retry with hint: {e}")
                    continue
                logger.error(f"OpenAI JSON parse failed after hint retry, skipping: {e}")
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
        }
        return await call_chat_api(url, headers, payload, self.timeout)
