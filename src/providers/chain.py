"""Provider Chain：多 Provider 容错编排。

按配置顺序尝试各 Provider，首个成功即返回；
全部失败则抛出最后一个异常（含所有 Provider 的错误摘要）。
"""

import logging

from ..models import Hackathon
from .base import LLMProvider

logger = logging.getLogger(__name__)


class ProviderChain:
    """按顺序尝试多个 Provider，失败自动 fallback。"""

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("ProviderChain requires at least one provider")
        self.providers = providers

    async def search(self, today: str) -> list[Hackathon]:
        """依次尝试各 Provider，首个成功即返回。

        全部失败时抛 RuntimeError，含所有尝试的错误摘要。
        """
        errors: list[str] = []
        for provider in self.providers:
            try:
                logger.info(f"Trying provider: {provider.name}")
                result = await provider.search(today)
                logger.info(f"Provider {provider.name} returned {len(result)} hackathons")
                # 标记来源
                for h in result:
                    h.source = provider.name
                return result
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                errors.append(f"{provider.name}: {e}")

        raise RuntimeError(f"All providers failed: {'; '.join(errors)}")


def build_provider_chain() -> ProviderChain:
    """根据环境变量构建 Provider Chain。

    环境变量：
    - LLM_PROVIDERS: 逗号分隔的 provider 列表（顺序即优先级），默认 "glm"
    - 各 provider 的 API_KEY/BASE_URL/MODEL 环境变量

    Returns:
        ProviderChain 实例
    """
    import os

    # 延迟导入避免循环依赖
    from .glm import GLMProvider
    from .openai_provider import OpenAICompatibleProvider

    registry: dict[str, type[LLMProvider]] = {
        "glm": GLMProvider,
        "openai": OpenAICompatibleProvider,
    }

    names = [n.strip() for n in os.environ.get("LLM_PROVIDERS", "glm").split(",") if n.strip()]
    providers: list[LLMProvider] = []
    for name in names:
        key = name.lower()
        if key not in registry:
            logger.warning(f"Unknown provider '{name}', skipping")
            continue
        cls = registry[key]
        provider = cls.from_env()
        if provider is not None:
            providers.append(provider)

    if not providers:
        # 兜底：尝试 GLM（main.py 已检查 LLM_API_KEY，此处一般不会到）
        glm = GLMProvider.from_env()
        if glm is not None:
            providers.append(glm)

    if not providers:
        raise ValueError("No LLM provider available: set LLM_API_KEY (GLM) and/or OPENAI_API_KEY")

    return ProviderChain(providers)
