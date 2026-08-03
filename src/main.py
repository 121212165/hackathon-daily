import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .email_renderer import render_email
from .mailer import ResendMailer
from .providers import build_provider_chain
from .store import get_unseen, mark_pushed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def beijing_today() -> str:
    """返回北京时区的今日日期字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def _require_env(name: str) -> str | None:
    """读取必填环境变量，缺失时记错误日志并返回 None。"""
    value = os.environ.get(name)
    if not value:
        logger.error(f"{name} is missing")
    return value


def _parse_recipients(mail_to: str) -> list[str]:
    """解析收件人：支持逗号分隔的多地址。"""
    return [e.strip() for e in mail_to.split(",") if e.strip()]


async def main() -> int:
    load_dotenv()
    today = beijing_today()
    logger.info(f"Starting hackathon daily for {today}")

    # 前置检查所有必填环境变量，避免 LLM 调用后才发现邮件配置缺失而浪费计费
    llm_api_key = _require_env("LLM_API_KEY")
    resend_api_key = _require_env("RESEND_API_KEY")
    mail_from = _require_env("MAIL_FROM")
    mail_to = _require_env("MAIL_TO")
    if not all([llm_api_key, resend_api_key, mail_from, mail_to]):
        return 1

    recipients = _parse_recipients(mail_to)

    # 1. 搜索（多 Provider 容错）
    try:
        chain = build_provider_chain()
    except ValueError as e:
        logger.error(f"Failed to build provider chain: {e}")
        return 1

    try:
        hackathons = await chain.search(today)
    except Exception as e:
        logger.error(f"LLM search failed: {e}")
        return 1

    logger.info(f"Found {len(hackathons)} hackathons")
    if not hackathons:
        logger.info("No hackathons today, skip sending")
        return 0

    # 2. 去重：仅推送未见过的
    unseen = get_unseen(hackathons)
    if not unseen:
        logger.info("No new hackathons (all already pushed), skip sending")
        return 0

    logger.info(f"{len(unseen)} new hackathons to send")

    # 3. 渲染
    subject, html = render_email(unseen, today)

    # 4. 发送
    mailer = ResendMailer(
        api_key=resend_api_key,
        from_email=mail_from,
        to_email=recipients,
    )
    try:
        await mailer.send(subject, html)
    except Exception as e:
        logger.error(f"Send email failed: {e}")
        return 1

    # 5. 标记已推送（仅发送成功后）
    mark_pushed(unseen)

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
