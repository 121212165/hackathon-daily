import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .email_renderer import render_email
from .llm_search import GLMSearchProvider
from .mailer import ResendMailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def beijing_today() -> str:
    """返回北京时区的今日日期字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


async def main() -> int:
    load_dotenv()
    today = beijing_today()
    logger.info(f"Starting hackathon daily for {today}")

    # 1. 搜索
    provider = GLMSearchProvider(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
        model=os.environ.get("LLM_MODEL", "glm-4-search"),
    )
    try:
        hackathons = await provider.search(today)
    except Exception as e:
        logger.error(f"LLM search failed: {e}")
        return 1

    logger.info(f"Found {len(hackathons)} hackathons")
    if not hackathons:
        logger.info("No hackathons today, skip sending")
        return 0

    # 2. 渲染
    subject, html = render_email(hackathons, today)

    # 3. 发送
    mailer = ResendMailer(
        api_key=os.environ["RESEND_API_KEY"],
        from_email=os.environ["MAIL_FROM"],
        to_email=os.environ["MAIL_TO"],
    )
    try:
        await mailer.send(subject, html)
    except Exception as e:
        logger.error(f"Send email failed: {e}")
        return 1

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
