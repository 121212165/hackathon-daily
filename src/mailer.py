import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class Mailer(ABC):
    @abstractmethod
    async def send(self, subject: str, html: str) -> None:
        ...


class ResendMailer(Mailer):
    """通过 Resend API 发送邮件，带 2 次重试。"""

    def __init__(self, api_key: str, from_email: str, to_email: str, timeout: float = 30.0):
        self.api_key = api_key
        self.from_email = from_email
        self.to_email = to_email
        self.timeout = timeout

    async def send(self, subject: str, html: str) -> None:
        url = "https://api.resend.com/emails"
        payload = {
            "from": self.from_email,
            "to": [self.to_email],
            "subject": subject,
            "html": html,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    logger.info(f"Email sent to {self.to_email}: {resp.json()}")
                    return
            except Exception as e:
                last_exc = e
                logger.warning(f"Resend attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(4 ** attempt)
        raise RuntimeError(f"Resend send failed after retries: {last_exc}")
