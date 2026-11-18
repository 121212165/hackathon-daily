"""store.py 去重持久化层测试。

覆盖：
- init_db 幂等（含 url_hash 列迁移）
- get_unseen 纯查询不写入
- mark_pushed 写入 + 两步 upsert（url_hash 优先，title_hash 兜底）
- 标题归一化去重（空白/大小写/标点）
- URL 归一化去重（utm / 大小写 / 尾斜杠）
- 老库（无 url_hash 列）读写兼容，老条目仍去重
- 非法/空 registration_url → 回退标题路径
- 发送失败不 mark → 下次仍 unseen
"""

import sqlite3

from src.models import Hackathon
from src.store import get_unseen, init_db, mark_pushed, normalize_url, title_hash, url_hash


def _make_hackathon(name="测试黑客松", url=None):
    """构造测试条目。url 为 None 时按标题生成独立报名链接（URL 才是身份）。"""
    if url is None:
        url = f"https://example.com/register/{name}"
    return Hackathon(
        name=name,
        organizer="主办方",
        type_tag="AI",
        summary="简介",
        registration_deadline="2026-08-01",
        start_date="2026-08-15",
        end_date="2026-08-17",
        location="线上",
        registration_url=url,
        detail_url=None,
    )


async def test_init_db_idempotent(tmp_path):
    """init_db 多次调用不报错。"""
    db = tmp_path / "test.db"
    init_db(db)
    init_db(db)  # 幂等
    assert db.exists()


async def test_get_unseen_empty_input(tmp_path):
    """空列表输入 → 返回空。"""
    db = tmp_path / "test.db"
    assert get_unseen([], db) == []


async def test_get_unseen_all_new(tmp_path):
    """全部新条目 → 全部返回。"""
    db = tmp_path / "test.db"
    items = [_make_hackathon("A"), _make_hackathon("B")]
    unseen = get_unseen(items, db)
    assert len(unseen) == 2


async def test_get_unseen_does_not_write(tmp_path):
    """get_unseen 是纯查询，不写入 → 再次调用仍全部 unseen。"""
    db = tmp_path / "test.db"
    items = [_make_hackathon("A")]
    get_unseen(items, db)
    # 再次查询，仍应全部 unseen（因为没调 mark_pushed）
    unseen = get_unseen(items, db)
    assert len(unseen) == 1


async def test_mark_pushed_then_unseen(tmp_path):
    """mark_pushed 后，相同条目不再 unseen。"""
    db = tmp_path / "test.db"
    items = [_make_hackathon("A"), _make_hackathon("B")]
    mark_pushed(items, db)

    # 相同条目 → 全部已见
    unseen = get_unseen(items, db)
    assert unseen == []

    # 新条目 → 返回新的
    new_item = _make_hackathon("C")
    unseen = get_unseen([_make_hackathon("A"), new_item], db)
    assert len(unseen) == 1
    assert unseen[0].name == "C"


async def test_title_normalization_dedup(tmp_path):
    """标题归一化：空白/大小写/标点差异应视为相同。"""
    db = tmp_path / "test.db"
    original = _make_hackathon("AI 黑客松 2026！")
    mark_pushed([original], db)

    # 不同空白、大小写、标点
    variants = [
        _make_hackathon("ai 黑客松 2026！"),
        _make_hackathon("AI黑客松2026"),
        _make_hackathon(" ai  黑客松  2026！ "),
    ]
    for v in variants:
        unseen = get_unseen([v], db)
        assert unseen == [], f"Should be deduped: {v.name}"


async def test_mark_pushed_upsert_updates_timestamp(tmp_path):
    """重复 mark_pushed 同一条目：更新 last_pushed_at 而非报错。"""
    db = tmp_path / "test.db"
    item = _make_hackathon("A")
    mark_pushed([item], db)
    mark_pushed([item], db)  # 不应报错


async def test_send_failure_retry_next_run(tmp_path):
    """模拟发送失败场景：不调 mark_pushed → 下次 get_unseen 仍返回。"""
    db = tmp_path / "test.db"
    items = [_make_hackathon("A")]
    # 第一次运行：搜索到但发送失败，未调 mark_pushed
    unseen_run1 = get_unseen(items, db)
    assert len(unseen_run1) == 1

    # 第二次运行：相同条目仍应 unseen（可重试）
    unseen_run2 = get_unseen(items, db)
    assert len(unseen_run2) == 1


async def test_title_hash_consistency():
    """相同标题（不同格式）hash 一致。"""
    h1 = _make_hackathon("AI 黑客松")
    h2 = _make_hackathon("ai黑客松")
    h3 = _make_hackathon(" AI  黑客松 ")
    assert title_hash(h1) == title_hash(h2) == title_hash(h3)


# ---- URL 身份（批次 0 / §2.2）----


def test_normalize_url_rules():
    """normalize_url：strip / 小写 scheme+host / 去 tracking / 去尾斜杠 / 非法 → None。"""
    assert normalize_url(None) is None
    assert normalize_url(123) is None
    assert normalize_url("") is None
    assert normalize_url("   ") is None
    assert normalize_url("javascript:alert(1)") is None  # 非 http(s) scheme
    assert normalize_url("example.com/x") is None  # 无 scheme
    assert normalize_url("HTTPS://Example.com/a/") == "https://example.com/a"
    assert normalize_url("https://example.com/") == "https://example.com"
    assert (
        normalize_url("https://example.com/a?utm_source=x&b=1&ref=y") == "https://example.com/a?b=1"
    )
    assert normalize_url("https://example.com/a?b=1#frag") == "https://example.com/a?b=1"


async def test_same_url_different_title_pushed_once(tmp_path):
    """同一 URL 不同标题 → 只推一次（URL 是稳定身份）。"""
    db = tmp_path / "test.db"
    mark_pushed([_make_hackathon("赛事原名", url="https://race.example.com/reg")], db)

    renamed = _make_hackathon("赛事改了新名字", url="https://race.example.com/reg")
    assert get_unseen([renamed], db) == []


async def test_url_variants_deduped(tmp_path):
    """URL 带 utm_* / 大小写 / 尾斜杠 / 首尾空白差异 → 判为同一条。"""
    db = tmp_path / "test.db"
    original = _make_hackathon("原始赛事", url="https://Example.com/reg?utm_source=tw&name=demo")
    mark_pushed([original], db)

    variants = [
        "https://example.com/reg?name=demo",
        "HTTPS://example.com/reg/?name=demo&utm_campaign=mail",
        "  https://example.com/reg?name=demo&ref=home  ",
        "https://example.com/reg?name=demo",
    ]
    for i, v in enumerate(variants):
        item = _make_hackathon(f"标题也各不相同{i}", url=v)
        assert get_unseen([item], db) == [], f"URL 变体应判为同一条: {v!r}"


async def test_invalid_url_falls_back_to_title(tmp_path):
    """registration_url 为空/非法 scheme → url_hash 为 None，回退 title_hash 路径。"""
    db = tmp_path / "test.db"
    broken = _make_hackathon("非法链接赛事", url="javascript:alert(1)")
    assert url_hash(broken) is None
    mark_pushed([broken], db)

    for bad in ["", "   ", "not-a-url", "ftp://example.com/x"]:
        item = _make_hackathon("非法链接赛事", url=bad)
        assert url_hash(item) is None
        assert get_unseen([item], db) == [], f"应回退标题去重: {bad!r}"

    # 标题不同 → 仍是新条目
    other = _make_hackathon("另一个赛事", url="")
    assert get_unseen([other], db) == [other]


async def test_legacy_db_without_url_hash_compat(tmp_path):
    """老库（建表时无 url_hash 列）：读写不炸、老条目仍去重、不爆发重推。"""
    db = tmp_path / "legacy.db"
    legacy_title = "老黑客松"
    legacy_schema = """
        CREATE TABLE hackathons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT,
            source TEXT NOT NULL DEFAULT 'llm',
            title_hash TEXT UNIQUE NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_pushed_at TEXT
        )
    """
    with sqlite3.connect(db) as conn:
        conn.execute(legacy_schema)
        conn.execute(
            "INSERT INTO hackathons (title, url, title_hash, first_seen_at) VALUES (?,?,?,?)",
            (
                legacy_title,
                "https://legacy.example.com/reg",
                title_hash(_make_hackathon(legacy_title)),
                "2026-01-01T00:00:00+08:00",
            ),
        )
        conn.commit()

    # 老条目（同标题、URL 不同/未知）→ 仍判为已推送
    assert get_unseen([_make_hackathon(legacy_title)], db) == []
    # 新条目正常
    fresh = _make_hackathon("新黑客松")
    assert get_unseen([fresh], db) == [fresh]

    # 迁移后可写：新行 + 老行回填 url_hash
    mark_pushed([fresh, _make_hackathon(legacy_title)], db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hackathons)")}
        assert "url_hash" in cols
        count = conn.execute("SELECT COUNT(*) FROM hackathons").fetchone()[0]
        backfilled = conn.execute(
            "SELECT url_hash FROM hackathons WHERE title_hash = ?",
            (title_hash(_make_hackathon(legacy_title)),),
        ).fetchone()
    assert count == 2, "同标题老行不应被重复插入"
    assert backfilled[0] is not None, "老行应回填 url_hash"

    # 迁移后再次查询仍稳定去重
    assert get_unseen([_make_hackathon(legacy_title), fresh], db) == []


async def test_get_unseen_does_not_touch_rows(tmp_path):
    """get_unseen 纯查询：不新增行、不回填 url_hash（发送失败重试语义不被破坏）。"""
    db = tmp_path / "test.db"
    mark_pushed([_make_hackathon("已有赛事")], db)
    query = "SELECT id, title, url, url_hash, last_pushed_at FROM hackathons ORDER BY id"
    with sqlite3.connect(db) as conn:
        before = conn.execute(query).fetchall()

    get_unseen([_make_hackathon("未见赛事"), _make_hackathon("已有赛事")], db)

    with sqlite3.connect(db) as conn:
        after = conn.execute(query).fetchall()
    assert after == before
    assert len(after) == 1
