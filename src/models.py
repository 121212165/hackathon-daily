import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

# 与 main.beijing_today() 保持一致：倒计时的一天以北京时间为准
_BEIJING_TZ = timezone(timedelta(hours=8))

# 这些域名是 LLM 照抄 system prompt 示例或编造的占位域名，不可能真的点开
_PLACEHOLDER_HOSTS = frozenset(
    {
        "example.com",
        "www.example.com",
        "example.org",
        "www.example.org",
        "example.net",
        "www.example.net",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    }
)

# LLM 会照抄 prompt 示例并派生出 example2.com / www.example3.com 等占位域名
# （dry-run 实测漏网：http://www.example2.com/registration）
_PLACEHOLDER_HOST_RE = re.compile(
    r"^(?:www\d*\.)?(?:example|test|sample)\d*\.(?:com|org|net)$"
)

# LLM 偶尔返回 [文字](url) 形式的链接
_MD_LINK_RE = re.compile(r"^\[.*?\]\((.+?)\)$")


def is_broken_link(url: object) -> bool:
    """判断链接是否不可能真正点开（占位域名 / 非法 scheme / 乱码 host）。

    这是「无效链接」的静态判定，不做网络请求（不阻塞发信流水线）：
    - 空值 / 非字符串 / 非 http(s) scheme → 无效
    - example.com / example.org / localhost 等占位域名 → 无效
    - host 含 ? 等乱码字符（如 www.csu????.org）→ 无效
    其余形态（含 markdown 包裹、尖括号）按清洗后的 URL 判定。
    """
    if not isinstance(url, str):
        return True
    text = url.strip()
    md = _MD_LINK_RE.match(text)
    if md:
        text = md.group(1).strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    if not text:
        return True
    # LLM 输出损坏时会出现 www.csu????.org 这类乱码 host（urlsplit 会把 ? 当 query 分隔符）
    if "??" in text:
        return True
    try:
        parsed = urlsplit(text)
        # 与 email_renderer.safe_url 保持一致：无 scheme 的裸域名按 https 处理
        if parsed.scheme == "":
            first = text.split("/", 1)[0]
            if not text.startswith("/") and first[:1].isalnum() and "." in first:
                parsed = urlsplit(f"https://{text}")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return True
    if parsed.scheme not in ("http", "https") or not host:
        return True
    if host in _PLACEHOLDER_HOSTS or _PLACEHOLDER_HOST_RE.match(host):
        return True
    if "?" in host or "*" in host:
        return True
    return False


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
    def detail_link(self) -> str:
        """赛事官网 / 详情页链接；占位或无效时返回空字符串。"""
        if is_broken_link(self.detail_url):
            return ""
        return str(self.detail_url).strip()

    @property
    def register_link(self) -> str:
        """邮件「立即报名」按钮实际跳转的地址（纯派生，不写入数据层）。

        优先用报名链接；若报名链接是 example.com 等无效链接，则回退到
        detail_url（赛事官网 / 详情页）；两者都无效时返回空字符串，
        渲染层据此隐藏按钮，避免用户点到死链。
        """
        if not is_broken_link(self.registration_url):
            return self.registration_url.strip()
        return self.detail_link

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
