from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

# 与 main.beijing_today() 保持一致：倒计时的一天以北京时间为准
_BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_date() -> date:
    """返回北京时区的今天（date），供倒计时与测试共用。"""
    return datetime.now(_BEIJING_TZ).date()


@dataclass
class Hackathon:
    """黑客松数据模型。"""

    name: str
    organizer: str
    type_tag: str
    summary: str
    registration_deadline: str
    start_date: str
    end_date: str
    location: str
    registration_url: str
    detail_url: str | None
    source: str = "llm"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hackathon":
        """从字典构造 Hackathon。registration_url 必填，缺失抛 ValueError。"""
        url = data.get("registration_url")
        if not url:
            raise ValueError("registration_url is required")
        return cls(
            name=data.get("name") or "未知",
            organizer=data.get("organizer") or "未知",
            type_tag=data.get("type_tag") or "未知",
            summary=data.get("summary") or "",
            registration_deadline=data.get("registration_deadline") or "待定",
            start_date=data.get("start_date") or "待定",
            end_date=data.get("end_date") or "待定",
            location=data.get("location") or "线上",
            registration_url=url,
            detail_url=data.get("detail_url"),
        )

    @property
    def days_left(self) -> int | None:
        """距报名截止的天数（纯派生，北京时区）。

        仅解析严格的 YYYY-MM-DD；缺省（"待定"/空）或格式非法返回 None。
        不写入 dataclass 字段，也不改变 from_dict / LLM 输出契约。
        """
        if not isinstance(self.registration_deadline, str):
            return None
        raw = self.registration_deadline.strip()
        if not raw:
            return None
        try:
            deadline = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None
        return (deadline - beijing_date()).days

    def urgency(self) -> str:
        """倒计时档位：hot(≤3 天) / soon(≤7 天) / later(更久) / unknown(无有效截止日期)。"""
        days = self.days_left
        if days is None:
            return "unknown"
        if days <= 3:
            return "hot"
        if days <= 7:
            return "soon"
        return "later"
