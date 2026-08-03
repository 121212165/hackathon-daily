"""LLM Provider 抽象基类。"""

from abc import ABC, abstractmethod

from ..models import Hackathon


class LLMProvider(ABC):
    """LLM 搜索提供商接口。

    每个 Provider 负责调用特定 LLM API 搜索黑客松信息。
    实现类需处理各自的鉴权、重试、错误分类逻辑。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 标识名，用于日志与 Hackathon.source 标记。"""

    @abstractmethod
    async def search(self, today: str) -> list[Hackathon]:
        """搜索黑客松，返回列表。

        Args:
            today: 北京时区今日日期字符串 (YYYY-MM-DD)

        Returns:
            Hackathon 列表，空列表表示无结果

        Raises:
            Exception: 调用失败时抛出，由 ProviderChain 决定是否 fallback
        """
