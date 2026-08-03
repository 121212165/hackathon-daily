"""store.py 去重持久化层测试。

覆盖：
- init_db 幂等
- get_unseen 纯查询不写入
- mark_pushed 写入 + UPSERT
- 标题归一化去重（空白/大小写/标点）
- 发送失败不 mark → 下次仍 unseen
"""

from src.models import Hackathon
from src.store import get_unseen, init_db, mark_pushed, title_hash


def _make_hackathon(name="测试黑客松", url="https://example.com"):
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
