"""SQLite 持久化层：记录已推送黑客松，支持跨次运行去重。

设计：
- get_unseen() 纯查询，不写入 → 发送失败时下次仍会重试
- mark_pushed() 写入/更新 → 仅发送成功后调用
- 去重身份：URL 归一化后 SHA256 为主键，标题 hash 兜底（老行/非法 URL）
  - 赛事改标题但 URL 不变 → 仍判为已推送（修「改标题就重复推送」）
  - 老库（迁移前只有 title_hash 数据）→ 仍按标题去重，绝不爆发重复推送
- 迁移：init_db() 幂等地 ALTER 加 url_hash 可空列 + 部分唯一索引，不重建表
"""

import hashlib
import logging
import re
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Hackathon

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "hackathons.db"

_BEIJING_TZ = timezone(timedelta(hours=8))

# tracking 参数：query 中命中（忽略大小写）即剔除，不参与身份计算
_TRACKING_PARAMS = {"ref", "from", "spm", "fbclid", "gclid", "mc_cid", "mc_eid"}
_TRACKING_PREFIXES = ("utm_",)


def _normalize_title(title: str) -> str:
    """归一化标题：去空白、转小写、去非字母数字字符。"""
    return re.sub(r"[\s\W_]+", "", title).lower()


def title_hash(hackathon: Hackathon) -> str:
    """计算标题归一化后的 SHA256 前 16 字符，用于兜底去重。"""
    return hashlib.sha256(_normalize_title(hackathon.name).encode()).hexdigest()[:16]


def normalize_url(url: object) -> str | None:
    """归一化报名 URL（去重身份用），非法输入返回 None（退回 title_hash 路径）。

    规则：
    1. 去首尾空白；scheme / host 转小写（path 保留大小写）
    2. 去 utm_* / ref / from / spm 等 tracking 参数
    3. 去末尾 `/`（`/x` 与 `/x/` 视为同一条）
    4. 只保留 http/https；空、非字符串、无 scheme 等 → None
    另：丢弃 fragment（#锚点不参与身份）。
    """
    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw:
        return None
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if not parts.netloc:
        return None

    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith(_TRACKING_PREFIXES) or k.lower() in _TRACKING_PARAMS)
    ]
    return urllib.parse.urlunsplit(
        (scheme, parts.netloc.lower(), parts.path.rstrip("/"), urllib.parse.urlencode(kept), "")
    )


def url_hash(hackathon: Hackathon) -> str | None:
    """URL 归一化后的 SHA256 前 16 字符；URL 非法/缺失时为 None。"""
    normalized = normalize_url(getattr(hackathon, "registration_url", None))
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库与表结构（幂等，含 url_hash 向后兼容迁移）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hackathons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT,
                source TEXT NOT NULL DEFAULT 'llm',
                title_hash TEXT UNIQUE NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_pushed_at TEXT,
                url_hash TEXT
            )
            """
        )
        # 老库迁移：只加可空列，绝不重建表（重建会让老行全部变成"新的"）
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hackathons)")}
        if "url_hash" not in columns:
            conn.execute("ALTER TABLE hackathons ADD COLUMN url_hash TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_hackathons_url_hash
            ON hackathons(url_hash) WHERE url_hash IS NOT NULL
            """
        )
        conn.commit()


def get_unseen(hackathons: list[Hackathon], db_path: Path = DEFAULT_DB_PATH) -> list[Hackathon]:
    """返回 DB 中不存在的黑客松（纯查询，不写入）。

    已推送判定：url_hash 命中，或 title_hash 命中（兼容未迁移的老行与非法 URL）。
    该判定是旧"仅标题"判定的超集 → 升级后不会把老条目重新当成新的（防爆发重推）。

    发送失败时不调用 mark_pushed，下次仍会重试这些条目。
    """
    if not hackathons:
        return []
    init_db(db_path)
    unseen: list[Hackathon] = []
    with sqlite3.connect(db_path) as conn:
        for h in hackathons:
            u_hash = url_hash(h)
            row = None
            if u_hash is not None:
                row = conn.execute(
                    "SELECT 1 FROM hackathons WHERE url_hash = ?", (u_hash,)
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT 1 FROM hackathons WHERE title_hash = ?", (title_hash(h),)
                ).fetchone()
            if row is None:
                unseen.append(h)
    logger.info(f"Dedup: {len(hackathons)} total, {len(unseen)} unseen")
    return unseen


def mark_pushed(hackathons: list[Hackathon], db_path: Path = DEFAULT_DB_PATH) -> None:
    """记录已推送：新条目插入，已有条目更新 last_pushed_at。

    冲突键 url_hash 优先，两步先查后写（不要求纯 SQL UPSERT）：
    - url_hash 命中 → 仅更新 last_pushed_at
    - 否则 title_hash 命中 → 更新 last_pushed_at；老行（url_hash 为 NULL）顺带回填 url_hash
    - 都未命中 → 插入新行（同时写 title_hash 与 url_hash）
    """
    if not hackathons:
        return
    init_db(db_path)
    now = datetime.now(_BEIJING_TZ).isoformat()
    with sqlite3.connect(db_path) as conn:
        for h in hackathons:
            h_title_hash = title_hash(h)
            h_url_hash = url_hash(h)
            source = getattr(h, "source", "llm")

            row = None
            if h_url_hash is not None:
                row = conn.execute(
                    "SELECT id FROM hackathons WHERE url_hash = ?", (h_url_hash,)
                ).fetchone()
            if row is not None:
                conn.execute("UPDATE hackathons SET last_pushed_at = ? WHERE id = ?", (now, row[0]))
                continue

            row = conn.execute(
                "SELECT id, url_hash FROM hackathons WHERE title_hash = ?", (h_title_hash,)
            ).fetchone()
            if row is not None:
                if h_url_hash is not None and row[1] is None:
                    # 老行迁移回填：标题命中且尚未记录 URL 身份
                    conn.execute(
                        "UPDATE hackathons SET last_pushed_at = ?, url_hash = ? WHERE id = ?",
                        (now, h_url_hash, row[0]),
                    )
                else:
                    conn.execute(
                        "UPDATE hackathons SET last_pushed_at = ? WHERE id = ?", (now, row[0])
                    )
                continue

            conn.execute(
                """
                INSERT INTO hackathons
                    (title, url, source, title_hash, url_hash, first_seen_at, last_pushed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (h.name, h.registration_url, source, h_title_hash, h_url_hash, now, now),
            )
        conn.commit()
    logger.info(f"Marked {len(hackathons)} hackathons as pushed")
