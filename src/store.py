"""SQLite 持久化层：记录已推送黑客松，支持跨次运行去重。

设计：
- get_unseen() 纯查询，不写入 → 发送失败时下次仍会重试
- mark_pushed() 写入/更新 → 仅发送成功后调用
- 标题归一化后 SHA256 去重，避免空白/大小写差异
"""

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Hackathon

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "hackathons.db"

_BEIJING_TZ = timezone(timedelta(hours=8))


def _normalize_title(title: str) -> str:
    """归一化标题：去空白、转小写、去非字母数字字符。"""
    return re.sub(r"[\s\W_]+", "", title).lower()


def title_hash(hackathon: Hackathon) -> str:
    """计算标题归一化后的 SHA256 前 16 字符，用于去重。"""
    return hashlib.sha256(_normalize_title(hackathon.name).encode()).hexdigest()[:16]


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库与表结构（幂等）。"""
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
                last_pushed_at TEXT
            )
            """
        )
        conn.commit()


def get_unseen(hackathons: list[Hackathon], db_path: Path = DEFAULT_DB_PATH) -> list[Hackathon]:
    """返回 DB 中不存在的黑客松（纯查询，不写入）。

    发送失败时不调用 mark_pushed，下次仍会重试这些条目。
    """
    if not hackathons:
        return []
    init_db(db_path)
    unseen: list[Hackathon] = []
    with sqlite3.connect(db_path) as conn:
        for h in hackathons:
            h_hash = title_hash(h)
            row = conn.execute(
                "SELECT 1 FROM hackathons WHERE title_hash = ?", (h_hash,)
            ).fetchone()
            if row is None:
                unseen.append(h)
    logger.info(f"Dedup: {len(hackathons)} total, {len(unseen)} unseen")
    return unseen


def mark_pushed(hackathons: list[Hackathon], db_path: Path = DEFAULT_DB_PATH) -> None:
    """记录已推送：新条目插入，已有条目更新 last_pushed_at。

    使用 UPSERT (ON CONFLICT) 语义：
    - 新条目：插入并记录 first_seen_at + last_pushed_at
    - 已有条目：仅更新 last_pushed_at
    """
    if not hackathons:
        return
    init_db(db_path)
    now = datetime.now(_BEIJING_TZ).isoformat()
    with sqlite3.connect(db_path) as conn:
        for h in hackathons:
            h_hash = title_hash(h)
            source = getattr(h, "source", "llm")
            conn.execute(
                """
                INSERT INTO hackathons
                    (title, url, source, title_hash, first_seen_at, last_pushed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(title_hash)
                    DO UPDATE SET last_pushed_at = excluded.last_pushed_at
                """,
                (h.name, h.registration_url, source, h_hash, now, now),
            )
        conn.commit()
    logger.info(f"Marked {len(hackathons)} hackathons as pushed")
