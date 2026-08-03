import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from .models import Hackathon

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一名国内线上黑客松信息聚合助手。
任务：搜索当前中国大陆地区仍可报名或正在进行中的线上黑客松、编程竞赛、创客马拉松。

筛选条件：
- 地域：中国大陆主办方或面向中国大陆参赛者
- 形式：必须是线上或含线上赛道
- 时间：报名截止日期 ≥ 今天，或比赛尚未结束
- 排除：纯线下赛事、已结束赛事、报名已截止赛事、无法获取报名链接的赛事

输出要求：
- 严格返回 JSON 数组，每个元素包含以下字段：
  - name: 赛事名称
  - organizer: 主办方
  - type_tag: 类型标签（如 AI/数据/全栈/创意）
  - summary: 一句话简介
  - registration_deadline: 报名截止日期 (YYYY-MM-DD 或 "待定")
  - start_date: 比赛开始日期 (YYYY-MM-DD 或 "待定")
  - end_date: 比赛结束日期 (YYYY-MM-DD 或 "待定")
  - location: "线上" 或包含线上描述
  - registration_url: 报名链接（必填）
  - detail_url: 官网或详情页链接（可选）
- 只返回 JSON，不包含 markdown 代码块标记或任何解释性文字
- 输出语言：中文

示例输出：
[
  {
    "name": "示例黑客松",
    "organizer": "示例主办方",
    "type_tag": "AI",
    "summary": "一句话简介",
    "registration_deadline": "2026-08-01",
    "start_date": "2026-08-15",
    "end_date": "2026-08-17",
    "location": "线上",
    "registration_url": "https://example.com/register",
    "detail_url": "https://example.com"
  }
]
"""

JSON_HINT = "请只返回合法 JSON 数组，不要包含任何 markdown 标记或解释性文字。"


class LLMSearchProvider(ABC):
    @abstractmethod
    async def search(self, today: str) -> list[Hackathon]: ...


class GLMSearchProvider(LLMSearchProvider):
    """通过智谱 GLM 联网搜索 API 获取黑客松列表。

    错误处理（匹配 spec 第 9 节）：
    - HTTP/网络错误：retry 2 次（指数退避 1s, 4s），仍失败 → 抛 RuntimeError → workflow 报错退出
    - JSON 解析错误：retry 1 次带 hint，仍失败 → 返回空列表 → main.py 跳过发送
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
                return self._parse(content)
            except ValueError as e:
                # JSON 解析错误：重试 1 次带 hint，仍失败则跳过当次发送（返回空列表）
                if not json_hint_used:
                    json_hint_used = True
                    logger.warning(f"JSON parse failed, will retry with hint: {e}")
                    continue
                logger.error(f"JSON parse failed after hint retry, skipping send: {e}")
                return []
        return []  # 不可达，保险兜底

    async def _call_api(self, messages: list[dict]) -> str:
        """调用 LLM API。

        重试策略（匹配 spec 第 9 节）：
        - 4xx 客户端错误：立即抛 RuntimeError，不重试（重试也必失败）。记录响应体便于定位。
        - 5xx 服务端错误 / 超时 / 网络错误：重试 2 次（指数退避 1s, 4s），仍失败抛 RuntimeError。
        - 响应结构异常（choices 缺失等）：抛 ValueError，触发上层 search() 的 JSON hint 重试。
        """
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
            # 模型本身用免费的 glm-4-flash，搜索引擎 search_std 按 ¥0.01/次 计费
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

        last_retryable_exc: Exception | None = None
        # 复用单一 AsyncClient，避免每次重试重建 TLS 连接
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    # 4xx：客户端错误，重试必失败，立即抛出并记录响应体供排查
                    if 400 <= resp.status_code < 500:
                        body = resp.text
                        logger.error(
                            f"GLM API client error {resp.status_code}, not retrying: {body}"
                        )
                        raise RuntimeError(f"GLM API {resp.status_code} client error: {body}")
                    # 5xx 与其他非 2xx：走重试
                    resp.raise_for_status()
                    data = resp.json()
                    # 响应结构异常：转 ValueError，让上层 search() 走 JSON hint 重试路径
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as e:
                        raise ValueError(
                            f"LLM response structure invalid: {e}, body: {data}"
                        ) from e
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError(f"LLM returned empty content, body: {data}")
                    return content
                except RuntimeError:
                    # 4xx 抛出的 RuntimeError，不重试，直接向上抛
                    raise
                except ValueError:
                    # 结构异常，交给上层 search() 处理（JSON hint 重试）
                    raise
                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as e:
                    last_retryable_exc = e
                    logger.warning(f"GLM search attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(4**attempt)
        raise RuntimeError(f"GLM search failed after retries: {last_retryable_exc}")

    @staticmethod
    def _parse(content: str) -> list[Hackathon]:
        """解析 LLM 返回的内容为 Hackathon 列表。"""
        text = content.strip()
        # 剥离 markdown 代码块围栏（支持单行 ```json [...] ``` 与多行形式）
        fence = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

        try:
            arr = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}")

        if not isinstance(arr, list):
            raise ValueError("LLM returned non-array")

        result: list[Hackathon] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            try:
                result.append(Hackathon.from_dict(item))
            except ValueError as e:
                logger.warning(f"Skip invalid hackathon entry: {e}")
        return result
