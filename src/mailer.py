import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class Mailer(ABC):
    @abstractmethod
    async def send(self, subject: str, html: str) -> None: ...


class ResendMailer(Mailer):
    """通过 Resend API 发送邮件，带 2 次重试。"""

    def __init__(
        self,
        api_key: str,
        from_email: str,
        to_email: str | list[str],
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.from_email = from_email
        # 归一化为 list：支持单地址或多地址（逗号分隔的环境变量已在外部拆分）
        self.to_emails = [to_email] if isinstance(to_email, str) else list(to_email)
        self.timeout = timeout

    async def send(self, subject: str, html: str) -> None:
        """发送邮件。

        重试策略：
        - 4xx 客户端错误（401 鉴权失败 / 422 邮件格式错误等）：立即抛 RuntimeError，不重试。
        - 5xx 服务端错误 / 超时 / 网络错误：重试 2 次（指数退避 1s, 4s），仍失败抛 RuntimeError。
        """
        url = "https://api.resend.com/emails"
        payload = {
            "from": self.from_email,
            "to": self.to_emails,
            "subject": subject,
            "html": html,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
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
                            f"Resend API client error {resp.status_code}, not retrying: {body}"
                        )
                        raise RuntimeError(f"Resend API {resp.status_code} client error: {body}")
                    resp.raise_for_status()
                    logger.info(f"Email sent to {self.to_emails}: {resp.json()}")
                    return
                except RuntimeError:
                    # 4xx 抛出的 RuntimeError，不重试，直接向上抛
                    raise
                except (
                    httpx.HTTPStatusError,
                    httpx.TimeoutException,
                    httpx.TransportError,
                ) as e:
                    last_retryable_exc = e
                    logger.warning(f"Resend attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(4**attempt)
        raise RuntimeError(f"Resend send failed after retries: {last_retryable_exc}")
