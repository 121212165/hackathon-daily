"""搜索 Provider 抽象层与编排。

- SearchProvider / LLMProvider（别名）：统一搜索源接口
- FallbackChain / ProviderChain（别名）：LLM 内部顺序兜底
- FanIn：顶层并发并集合并入口（build_provider_chain() 返回）
"""

from .base import LLMProvider, SearchProvider
from .chain import FallbackChain, ProviderChain, build_provider_chain
from .fanin import FanIn

__all__ = [
    "FallbackChain",
    "FanIn",
    "LLMProvider",
    "ProviderChain",
    "SearchProvider",
    "build_provider_chain",
]
