from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Hackathon

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def safe_url(url: str) -> str:
    """过滤非 http/https 协议的 URL，防止 javascript: 等危险 scheme。"""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", ""):
        return url
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
