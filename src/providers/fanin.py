"""FanIn：顶层搜索入口，并发执行所有源并取并集合并。

语义（计划 §2.1）：
- 并发执行配置的源；按 normalize_url() 归一化 + 标题兜底去重；
- 单源失败只 warning，不影响其它源；
- 全部源都失败才抛 RuntimeError（含逐源错误摘要）。
"""

import asyncio
import logging

from ..models import Hackathon
from ..store import normalize_url, title_hash

logger = logging.getLogger(__name__)


class FanIn:
    """并发多源合并器；接口与旧 ProviderChain 一致：search(today)。"""

    name = "fanin"

    def __init__(self, sources: list):
        if not sources:
            raise ValueError("FanIn requires at least one search source")
        self.sources = list(sources)
        # 兼容旧测试/调用方对 .providers 的引用
        self.providers = self.sources

    @staticmethod
    def _dedup_key(h: Hackathon) -> str:
        normalized = normalize_url(getattr(h, "registration_url", None))
        if normalized is not None:
            return f"url:{normalized}"
        return f"title:{title_hash(h)}"

    async def search(self, today: str) -> list[Hackathon]:
        outcomes = await asyncio.gather(
            *(source.search(today) for source in self.sources),
            return_exceptions=True,
        )

        merged: list[Hackathon] = []
        seen: set[str] = set()
        errors: list[str] = []

        for source, outcome in zip(self.sources, outcomes):
            if isinstance(outcome, BaseException):
                message = f"{source.name}: {outcome}"
                logger.warning(f"Search source {source.name} failed: {outcome}")
                errors.append(message)
                continue
            if not isinstance(outcome, list):
                message = f"{source.name}: invalid result type {type(outcome).__name__}"
                logger.warning(message)
                errors.append(message)
                continue

            for hackathon in outcome:
                hackathon.source = source.name
                key = self._dedup_key(hackathon)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(hackathon)

        if len(errors) == len(self.sources):
            raise RuntimeError("All search sources failed: " + "; ".join(errors))
        if errors:
            logger.warning(f"{len(errors)}/{len(self.sources)} search sources failed")
        return merged
