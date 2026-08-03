"""Provider 共享逻辑：系统 prompt、JSON 解析、重试。"""

import asyncio
import json
import logging
import re

import httpx

from ..models import Hackathon

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


def parse_hackathons(content: str) -> list[Hackathon]:
    """解析 LLM 返回的内容为 Hackathon 列表。

    支持 markdown 代码块围栏剥离。解析失败抛 ValueError。
    """
    text = content.strip()
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


async def call_chat_api(
    url: str,
    headers: dict,
    payload: dict,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> str:
    """通用 chat completions API 调用，含 4xx/5xx 分类重试。

    - 4xx：立即抛 RuntimeError（不重试），记录响应体
    - 5xx/超时/网络：重试，指数退避
    - 响应结构异常：抛 ValueError（触发上层 JSON hint 重试）

    Returns:
        LLM 返回的 content 字符串
    """
    last_retryable_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if 400 <= resp.status_code < 500:
                    body = resp.text
                    logger.error(f"API client error {resp.status_code}, not retrying: {body}")
                    raise RuntimeError(f"API {resp.status_code} client error: {body}")
                resp.raise_for_status()
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise ValueError(f"LLM response structure invalid: {e}, body: {data}") from e
                if not isinstance(content, str) or not content.strip():
                    raise ValueError(f"LLM returned empty content, body: {data}")
                return content
            except RuntimeError:
                raise
            except ValueError:
                raise
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as e:
                last_retryable_exc = e
                logger.warning(f"API attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(4**attempt)
    raise RuntimeError(f"API call failed after {max_retries} retries: {last_retryable_exc}")
