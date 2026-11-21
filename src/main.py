import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .email_renderer import render_email, render_empty_email
from .link_check import filter_reachable
from .mailer import ResendMailer
from .models import Hackathon
from .providers import build_provider_chain
from .store import count_pushed_last_7_days, get_unseen, mark_pushed

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


def _upcoming_top3(hackathons: list[Hackathon]) -> list[Hackathon]:
    """从当日搜索结果里取即将截止（≤3 天）的 TOP3，按 days_left 升序（只读）。"""
    candidates = [
        h for h in hackathons if isinstance(getattr(h, "days_left", None), int)
    ]
    candidates.sort(key=lambda h: h.days_left)
    return [h for h in candidates if h.days_left <= 3][:3]


# 任一 LLM provider key 即可开跑：各 provider 由 from_env() 自行认领自己的 key
PROVIDER_KEY_ENVS = ("LLM_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY")


def _provider_key_present() -> bool:
    """至少配置一个 provider key 即通过预检（只配 OPENAI_API_KEY 也应可用）。"""
    return any(os.environ.get(name) for name in PROVIDER_KEY_ENVS)


async def main() -> int:
    load_dotenv()
    today = beijing_today()
    dry_run = os.environ.get("DRY_RUN") == "1"
    logger.info(f"Starting hackathon daily for {today}" + (" [DRY-RUN]" if dry_run else ""))

    # 前置检查环境变量，避免搜索调用后才发现邮件配置缺失而浪费计费
    # Provider key：LLM/GLM/OPENAI 任一即可（各自 provider 认领）；邮件三项仍硬必填
    if not _provider_key_present():
        logger.error(
            f"No LLM provider key found: set at least one of {' / '.join(PROVIDER_KEY_ENVS)}"
        )
        return 1
    resend_api_key = _require_env("RESEND_API_KEY")
    mail_from = _require_env("MAIL_FROM")
    mail_to = _require_env("MAIL_TO")
    if not all([resend_api_key, mail_from, mail_to]):
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

    # 1b. 报名链接可达性校验：杜撰 / 死链在发信前拦下，避免用户点到死链
    hackathons, dropped = await filter_reachable(hackathons)
    for item in dropped:
        logger.warning(
            f"[link-check] dropped '{item.name}': {item.url} ({item.reason})"
        )
    if dropped:
        logger.warning(f"[link-check] dropped {len(dropped)} unreachable link(s)")
    logger.info(f"{len(hackathons)} hackathons with reachable links")

    # 搜索彻底失败（异常）已在上面 return 1；返回空列表视为"今天没搜到"，
    # 故障不伪装成日报 —— 这两种路径都不发邮件。
    if not hackathons:
        logger.info("No hackathons found today, skip sending")
        return 0

    # 2. 去重：仅推送未见过的
    unseen = get_unseen(hackathons)

    mailer = ResendMailer(
        api_key=resend_api_key,
        from_email=mail_from,
        to_email=recipients,
    )

    # 3a. 空日也发：搜索有结果但全部已推送 → 发「今日无新增」，且不标记（本来就是空集）
    if not unseen:
        logger.info("No new hackathons, sending empty-day digest")
        subject, html, text = render_empty_email(
            _upcoming_top3(hackathons),
            count_pushed_last_7_days(),
            today,
        )
        if dry_run:
            logger.info(f"[DRY-RUN] would send empty-day digest: {subject}")
            return 0
        try:
            await mailer.send(subject, html, text)
        except Exception as e:
            logger.error(f"Send empty-day email failed: {e}")
            return 1
        logger.info("Done (empty-day digest sent)")
        return 0

    # 3b. 非空日报
    logger.info(f"{len(unseen)} new hackathons to send")
    subject, html, text = render_email(unseen, today)

    if dry_run:
        logger.info(f"[DRY-RUN] subject: {subject}")
        for h in unseen:
            logger.info(f"[DRY-RUN] {h.name} -> {h.register_link}")
        logger.info("[DRY-RUN] no email sent, no db changes")
        return 0

    # 4. 发送
    try:
        await mailer.send(subject, html, text)
    except Exception as e:
        logger.error(f"Send email failed: {e}")
        return 1

    # 5. 标记已推送（仅发送成功后）
    mark_pushed(unseen)

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
