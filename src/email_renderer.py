import re
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Hackathon

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# 匹配 markdown 链接 [text](url) 形式
_MARKDOWN_LINK_RE = re.compile(r"^\[.*?\]\((.+?)\)$")


def safe_url(url: str) -> str:
    """规范化 URL，确保 href 可被邮件客户端正确识别为绝对链接。

    处理顺序：
    1. 空值/非字符串 → "#"
    2. 去除首尾空白
    3. 剥离 markdown 链接包裹（[text](url) → url）和尖括号 <url>
    4. 已是 http/https → 原样返回
    5. 无 scheme 但形如域名（www.xxx 或 xxx.yyy/...）→ 补 https://
    6. 其他（javascript:、mailto:、纯文本等）→ "#"
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


def render_email(hackathons: list[Hackathon], today: str) -> tuple[str, str]:
    """渲染邮件，返回 (subject, html)。"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["safe_url"] = safe_url
    template = env.get_template("daily_email.html.j2")
    html = template.render(hackathons=hackathons, today=today, count=len(hackathons))
    subject = f"黑客松日报 - {today}（{len(hackathons)} 场可报名）"
    return subject, html
