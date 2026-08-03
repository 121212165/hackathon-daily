"""LLM Provider 抽象层。

提供多 Provider 容错：按配置顺序尝试，失败自动 fallback。
"""

from .base import LLMProvider
from .chain import ProviderChain, build_provider_chain

__all__ = ["LLMProvider", "ProviderChain", "build_provider_chain"]
