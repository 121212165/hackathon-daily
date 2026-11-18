"""Provider 编排。

- FallbackChain：LLM 内部**顺序兜底**（首个非空结果即返回），语义不变；
  本次补上「空列表也算失败，继续 fallback」。
- build_provider_chain()：组装顶层 FanIn，作为 main.py 唯一搜索入口。
"""

import logging
import os
from typing import TYPE_CHECKING

from ..models import Hackathon
from .base import LLMProvider

if TYPE_CHECKING:
    from .fanin import FanIn

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_SOURCES = "devpost,mlh,clist,serper,tavily,glm"
DEFAULT_LLM_PROVIDERS = "glm,openai"


class FallbackChain:
    """按顺序尝试多个 Provider，取第一个非空结果；全部失败抛 RuntimeError。"""

    name = "llm-fallback"

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("ProviderChain requires at least one provider")
        self.providers = providers

    async def search(self, today: str) -> list[Hackathon]:
        errors: list[str] = []
        succeeded_empty = False
        for provider in self.providers:
            try:
                logger.info(f"Trying LLM provider: {provider.name}")
                result = await provider.search(today)
                if not result:
                    # 空结果也算失败：修「首个 provider 返回空就短路」的召回漏洞
                    logger.warning(f"Provider {provider.name} returned empty result, fallback")
                    succeeded_empty = True
                    continue
                for h in result:
                    h.source = provider.name
                return result
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                errors.append(f"{provider.name}: {e}")

        if succeeded_empty:
            # 有 provider 正常返回但今日无结果 → 不是故障（批次 2 的空日邮件依赖此语义）
            return []
        raise RuntimeError(f"All providers failed: {'; '.join(errors)}")


# 兼容旧引用（ProviderChain 语义已并入 FallbackChain）
ProviderChain = FallbackChain


def _build_llm_providers(llm_registry: dict[str, type[LLMProvider]]) -> list[LLMProvider]:
    """按 LLM_PROVIDERS 顺序构建兜底链；名单未产出任何实例时按注册表兜底。"""
    from .glm import GLMProvider
    from .openai_provider import OpenAICompatibleProvider

    names = [
        n.strip().lower()
        for n in os.environ.get("LLM_PROVIDERS", DEFAULT_LLM_PROVIDERS).split(",")
        if n.strip()
    ]
    providers: list[LLMProvider] = []
    for name in names:
        cls = llm_registry.get(name)
        if cls is None:
            logger.warning(f"Unknown LLM provider '{name}', skipping")
            continue
        provider = cls.from_env()
        if provider is not None:
            providers.append(provider)

    if not providers:
        # 配置名单未产出任何 provider（如只配 OPENAI_API_KEY）→ 按注册表认领
        for cls in (GLMProvider, OpenAICompatibleProvider):
            provider = cls.from_env()
            if provider is not None:
                providers.append(provider)
    return providers


def build_provider_chain() -> "FanIn":
    """构建顶层 FanIn。

    环境变量：
    - SEARCH_SOURCES: 逗号分隔，默认 devpost,mlh,clist,serper,tavily,glm
      （"glm" 表示 LLM 兜底链，计费源排最后；空/未设置 = 使用默认值）
    - LLM_PROVIDERS: LLM 内部兜底顺序，默认 "glm,openai"

    Raises:
        ValueError: 完全没有可用 provider key（保持批次 0 的预检语义）。
    """
    # 延迟导入避免循环依赖
    from .clist import ClistProvider
    from .devpost import DevpostProvider
    from .fanin import FanIn
    from .glm import GLMProvider
    from .mlh import MLHProvider
    from .openai_provider import OpenAICompatibleProvider
    from .serper import SerperProvider
    from .tavily import TavilyProvider

    llm_registry: dict[str, type[LLMProvider]] = {
        "glm": GLMProvider,
        "openai": OpenAICompatibleProvider,
    }
    source_registry: dict[str, type[LLMProvider]] = {
        "devpost": DevpostProvider,
        "mlh": MLHProvider,
        "clist": ClistProvider,
        "serper": SerperProvider,
        "tavily": TavilyProvider,
    }

    llm_providers = _build_llm_providers(llm_registry)
    if not llm_providers:
        raise ValueError("No LLM provider available: set LLM_API_KEY (GLM) and/or OPENAI_API_KEY")
    llm_chain = FallbackChain(llm_providers)

    raw_sources = os.environ.get("SEARCH_SOURCES", DEFAULT_SEARCH_SOURCES).strip()
    names = [
        n.strip().lower()
        for n in (raw_sources or DEFAULT_SEARCH_SOURCES).split(",")
        if n.strip()
    ]
    sources: list[LLMProvider | FallbackChain] = []
    llm_added = False
    for name in names:
        if name in llm_registry:
            # LLM 源统一走 FallbackChain，只放一次
            if not llm_added:
                sources.append(llm_chain)
                llm_added = True
            continue
        cls = source_registry.get(name)
        if cls is None:
            logger.warning(f"Unknown search source '{name}', skipping")
            continue
        provider = cls.from_env()
        if provider is None:
            logger.warning(f"Search source '{name}' is not configured, skipping")
            continue
        sources.append(provider)

    if not llm_added:
        sources.append(llm_chain)  # 计费源排最后
    return FanIn(sources)
