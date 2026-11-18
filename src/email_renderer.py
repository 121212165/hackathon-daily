import re
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Hackathon

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# 匹配 markdown 链接 [text](url) 形式
_MARKDOWN_LINK_RE = re.compile(r"^\[.*?\]\((.+?)\)$")

# 控制字符（C0 + DEL）— 邮件 href 中不应出现，防止 LLM 返回被污染的 URL
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# 分组顺序：hot → soon → later/unknown。分组只存在于渲染层，不写入数据层。
_GROUPS = (
    ("hot", "🔥 即将截止 (≤3 天)"),
    ("soon", "📌 本周 (≤7 天)"),
    ("later", "📅 后续"),
)

# 两套视觉：bold = 2026 酸性粗野（默认，向后兼容）；calm = 收敛版（仅留酸性色 + 等宽标签）
_STYLES = ("bold", "calm")


def _template_name(kind: str, style: str) -> str:
    """按风格选模板；style 非法时直接报错，避免悄悄回退到错误版本。"""
    if style not in _STYLES:
        raise ValueError(f"unknown email style: {style!r} (expected one of {_STYLES})")
    suffix = "" if style == "bold" else "_calm"
    return f"{kind}{suffix}.html.j2"


def safe_url(url: str) -> str:
    """规范化 URL，确保 href 可被邮件客户端正确识别为绝对链接。

    处理顺序：
    1. 空值/非字符串 → "#"
    2. 去除首尾空白
    3. 剥离 markdown 链接包裹（[text](url) → url）和尖括号 <url>
    4. 去除控制字符（防止 href 属性被污染）
    5. 已是 http/https → 原样返回
    6. 无 scheme 但形如域名（www.xxx 或 xxx.yyy/...）→ 补 https://
    7. 其他（javascript:、mailto:、纯文本等）→ "#"
    """
    if not url or not isinstance(url, str):
        return "#"

    url = url.strip()

    # 剥离 markdown 链接 [text](url)
    md_match = _MARKDOWN_LINK_RE.match(url)
    if md_match:
        url = md_match.group(1).strip()

    # 剥离尖括号包裹 <url>
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()

    # 去除控制字符（\t \n \r 等），防止 LLM 返回的 URL 污染 href 属性
    url = _CONTROL_CHARS_RE.sub("", url)

    if not url:
        return "#"

    parsed = urlparse(url)

    # 已有 http/https scheme，直接返回
    if parsed.scheme in ("http", "https"):
        return url

    # 无 scheme：判断是否像域名
    # 要求第一段以字母数字开头且含 "."，排除相对路径（../foo、./bar、register）
    if parsed.scheme == "" and not url.startswith("/"):
        first_segment = url.split("/", 1)[0]
        if first_segment[:1].isalnum() and "." in first_segment:
            return f"https://{url}"

    # 其他情况（javascript:、mailto:、相对路径、纯文本等）→ 不可点击
    return "#"


def _env() -> Environment:
    """构造 Jinja2 环境：自动转义 + safe_url 过滤器（防 URL / HTML 注入）。"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        # .html.j2 的后缀是 j2，须显式列入，否则 select_autoescape 不会开启自动转义
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    env.filters["safe_url"] = safe_url
    return env


def _sort_key(h: Hackathon) -> tuple[int, int]:
    """days_left 升序；无截止日期（None）排最后。"""
    days = h.days_left
    if days is None:
        return (1, 0)
    return (0, days)


def _prepare(hackathons: list[Hackathon]) -> tuple[list[dict], dict[str, int]]:
    """排序 + 分组 + 统计条。HTML 版与纯文本版共用同一份结果。"""
    ordered = sorted(hackathons, key=_sort_key)
    buckets: dict[str, list[Hackathon]] = {"hot": [], "soon": [], "later": []}
    for h in ordered:
        urgency = h.urgency()
        bucket = urgency if urgency in buckets else "later"
        buckets[bucket].append(h)

    groups = [
        {"key": key, "label": label, "entries": buckets[key]} for key, label in _GROUPS
    ]
    hot = len(buckets["hot"])
    soon = len(buckets["soon"])
    stats = {
        "new": len(hackathons),  # 今日新增（去重后待推送条数）
        "hot": hot,  # 即将截止（≤3 天）
        "week": hot + soon,  # 本周累计（≤7 天）
    }
    return groups, stats


def _render_text(groups: list[dict], stats: dict[str, int], subject: str) -> str:
    """纯文本版：分组小节 + "- " 列表 + 截止日期前缀，作为 multipart/alternative。"""
    lines = [
        subject,
        "",
        f"今日新增 {stats['new']} 场 · 即将截止 {stats['hot']} 场 · 本周累计 {stats['week']} 场",
        "",
    ]
    for group in groups:
        if not group["entries"]:
            continue
        lines.append(f"【{group['label']}】")
        for h in group["entries"]:
            lines.append(f"- [截止 {h.registration_deadline}] {h.name}（{h.organizer}）")
            lines.append(f"  报名: {safe_url(h.registration_url)}")
            if h.detail_url:
                lines.append(f"  详情: {safe_url(h.detail_url)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_email(
    hackathons: list[Hackathon], today: str, style: str = "bold"
) -> tuple[str, str, str]:
    """渲染日报，返回 (subject, html, text)。subject 格式保持不变以兼容既有测试。

    style="bold"（默认）= 酸性粗野；style="calm" = 收敛版（酸性色 + 等宽标签）。
    """
    groups, stats = _prepare(hackathons)
    subject = f"黑客松日报 - {today}（{len(hackathons)} 场可报名）"
    html = _env().get_template(_template_name("daily_email", style)).render(
        hackathons=hackathons,
        today=today,
        count=len(hackathons),
        groups=groups,
        stats=stats,
    )
    return subject, html, _render_text(groups, stats, subject)


def render_empty_email(
    top_upcoming: list[Hackathon], weekly_count: int, today: str, style: str = "bold"
) -> tuple[str, str, str]:
    """渲染「今日无新增」邮件，返回 (subject, html, text)。

    top_upcoming：从当日搜索结果里按 days_left 升序取出的即将截止 TOP3（只读）。
    weekly_count：来自 store.count_pushed_last_7_days()（只读查询）。
    style 同 render_email：bold（默认）/ calm。
    """
    subject = f"黑客松日报 - {today}（今日无新增）"
    html = _env().get_template(_template_name("empty", style)).render(
        top=top_upcoming,
        weekly_count=weekly_count,
        today=today,
    )
    lines = [subject, "", f"今日无新增 · 本周累计 {weekly_count} 场"]
    if top_upcoming:
        lines += ["", "【即将截止 TOP3】"]
        for h in top_upcoming:
            lines.append(f"- [截止 {h.registration_deadline}] {h.name}（{h.organizer}）")
            lines.append(f"  报名: {safe_url(h.registration_url)}")
    return subject, html, "\n".join(lines).rstrip() + "\n"
