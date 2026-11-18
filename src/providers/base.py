"""搜索 Provider 抽象基类。

所有搜索源（结构化站、SERP、LLM）统一实现该接口；
顶层 FanIn 并发执行各源并合并结果。
"""

from abc import ABC, abstractmethod
from typing import Self

from ..models import Hackathon


class SearchProvider(ABC):
    """搜索源接口。

    实现类各自处理鉴权、重试与错误分类：
    - 未配置（缺 key）→ from_env() 返回 None，组装时跳过；
    - 调用失败 → search() 抛出，由 FanIn / FallbackChain 隔离或兜底。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 标识，用于日志与 Hackathon.source 标记。"""

    @abstractmethod
    async def search(self, today: str) -> list[Hackathon]:
        """搜索黑客松；空列表表示本次无结果。

        Args:
            today: 北京时区今日日期字符串 (YYYY-MM-DD)
        """

    @classmethod
    def from_env(cls) -> Self | None:
        """从环境变量构建；未配置时返回 None（链上跳过）。

        无需环境变量的源（如 Devpost / MLH）直接返回实例；
        简单测试子类可覆盖或直接使用此默认实现。
        """
        return None


# 兼容旧引用（批次 1 之前的 LLMProvider 名称）
LLMProvider = SearchProvider
