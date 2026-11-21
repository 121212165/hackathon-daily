"""Provider 共享逻辑：系统 prompt、JSON 解析、重试。"""

import asyncio
import json
import logging
import os
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
  - registration_url: 报名链接（必填，必须是搜索结果里真实存在的网址）
  - detail_url: 官网或详情页链接（可选，必须是搜索结果里真实存在的网址）
- 严禁使用 example.com / example.org / example.net / localhost 等占位域名，严禁编造域名；
  找不到真实报名链接就不要输出该赛事，绝不能照抄下面示例里的占位符
- 只返回 JSON，不包含 markdown 代码块标记或任何解释性文字
- 输出语言：中文

示例输出（仅演示字段结构，URL 为占位符，实际输出必须换成搜索到的真实链接）：
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
    "registration_url": "<真实报名链接>",
    "detail_url": "<真实官网链接>"
  }
]
"""

JSON_HINT = "请只返回合法 JSON 数组，不要包含任何 markdown 标记或解释性文字。"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(content: str) -> list[dict]:
    """从 LLM 文本中抽取合法的 Hackathon 字典列表。

    复用 parse_hackathons 的围栏剥离 + json.loads + 逐条 from_dict 容错：
    - 整段不是 JSON 数组 → ValueError（由调用方决定是否 hint 重试）
    - 单条缺 registration_url / 类型错误 → 记 warning 并跳过，不影响其它条目

    返回原始字典（已通过 Hackathon.from_dict 校验），供 LLM / Serper / Tavily 共用。
    """
    text = (content or "").strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()

    try:
        arr = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    if not isinstance(arr, list):
        raise ValueError("LLM returned non-array")

    result: list[dict] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        try:
            Hackathon.from_dict(item)
        except ValueError as e:
            logger.warning(f"Skip invalid hackathon entry: {e}")
            continue
        result.append(item)
    return result


def parse_hackathons(content: str) -> list[Hackathon]:
    """解析 LLM 返回的内容为 Hackathon 列表（解析失败抛 ValueError）。"""
    return [Hackathon.from_dict(item) for item in extract_json(content)]


STRUCTURE_PROMPT = """你是信息抽取助手。下面是一组网页搜索结果（标题/链接/摘要/正文）。
请把其中仍可报名的中国大陆线上黑客松抽取为 JSON 数组，每项字段：
name, organizer, type_tag, summary, registration_deadline, start_date, end_date,
location, registration_url（必填，取搜索结果中的真实链接）, detail_url。
只保留确有报名链接的条目；无对应信息填 "待定" 或 ""。
链接必须取自搜索结果原文，严禁使用 example.com 等占位域名或编造域名。
只返回 JSON 数组，不包含 markdown 代码块或解释文字，输出语言为中文。"""


def _structure_llm_config() -> tuple[str, dict[str, str], str] | None:
    """返回廉价结构化调用的 (url, headers, model)；无可用 LLM key → None。"""
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GLM_API_KEY")
    if api_key:
        base = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        return (
            f"{base.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            "glm-4-flash",  # 结构化是廉价任务，固定用 flash 档
        )
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
        return (
            f"{base.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            "deepseek-chat",
        )
    return None


def ground_urls(items: list[dict], evidence: str) -> list[dict]:
    """硬校验：丢弃 URL 未出现在搜索结果原文中的条目（防 LLM 杜撰链接）。

    prompt 里的「严禁编造域名」只是软约束；这里做字符串级硬校验。
    比对时去掉 scheme 与首尾斜杠，容忍搜索结果的 http/https 差异；
    detail_url 未出现在原文则置空（保留该条目）。
    """
    kept: list[dict] = []
    for item in items:
        reg = str(item.get("registration_url") or "").strip()
        core = reg.split("://", 1)[-1].strip("/")
        if core and core not in evidence and reg not in evidence:
            logger.warning(f"Drop ungrounded registration URL: {reg}")
            continue

        det = str(item.get("detail_url") or "").strip()
        if det:
            det_core = det.split("://", 1)[-1].strip("/")
            if det_core not in evidence and det not in evidence:
                logger.warning(f"Drop ungrounded detail URL: {det}")
                item["detail_url"] = None
        kept.append(item)
    return kept


async def structure_search_results(items: list[dict], today: str) -> list[dict]:
    """SERP 结果 → 一次便宜 LLM 调用 → extract_json 结构化（+ URL 证据绑定）。

    失败（无 LLM key / 调用失败 / JSON 解析失败）只 warning 并返回空列表，
    不阻塞其它搜索源。
    """
    if not items:
        return []
    config = _structure_llm_config()
    if config is None:
        logger.warning("No LLM key available for SERP structuring, skipping")
        return []
    url, headers, model = config
    evidence = json.dumps(items[:20], ensure_ascii=False)[:12000]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": STRUCTURE_PROMPT},
            {"role": "user", "content": f"今天是 {today}。搜索结果如下：\n{evidence}"},
        ],
        "stream": False,
    }
    try:
        content = await call_chat_api(url, headers, payload, timeout=30.0, max_retries=1)
        return ground_urls(extract_json(content), evidence)
    except (ValueError, RuntimeError) as e:
        logger.warning(f"SERP structuring failed: {e}")
        return []


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
