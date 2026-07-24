from dataclasses import dataclass
from typing import Any


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
