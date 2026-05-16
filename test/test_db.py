"""Core DB flows: entries, companion sessions, media queues, history, archiver."""

from datetime import datetime, timedelta, timezone

import pytest
import app.db as db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_journal_entry_and_mood():
    eid = db.save_entry("journal", "user", "calm day")
    db.save_mood(eid, 0.5, 0.4, "positive", ["happy"], "{}")

    rows = db.get_history("timeline")
    assert any(r["id"] == eid and r.get("category") == "positive" for r in rows)


def test_companion_session_messages():
    sid = "companion-sess"
    db.save_entry("companion", "user", "hello", session_id=sid)
    db.save_entry("companion", "assistant", "hi there", session_id=sid)
    msgs = db.get_session_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_corpus_entries_user_only_incremental():
    e1 = db.save_entry("journal", "user", "first")
    e2 = db.save_entry("journal", "user", "second")
    db.save_entry("companion", "assistant", "reply")

    new = db.get_corpus_entries(since_id=e1)
    ids = {e["id"] for e in new}
    assert e2 in ids
    assert all(e["content"] != "reply" for e in new)


def test_pending_audio_and_image_queues():
    aid = db.save_audio_file("voice.webm", 100, None)
    db.save_entry("journal", "user", "", source="voice", audio_id=aid)
    assert any(p["audio_id"] == aid for p in db.get_pending_audio_entries())

    iid = db.save_image_file("photo.jpg", "image/jpeg", 1000)
    db.save_entry("journal", "user", "", source="image", image_id=iid)
    assert any(p["image_id"] == iid for p in db.get_pending_image_entries())


def test_history_and_stats_for_insights():
    e1 = db.save_entry("journal", "user", "morning")
    db.save_mood(e1, 0.4, 0.5, "positive", ["happy"], "{}")

    timeline = db.get_history("timeline")
    assert timeline and "content" in timeline[0]

    calendar = db.get_history("calendar")
    assert calendar and "day" in calendar[0]

    stats = db.get_stats()
    assert stats["daily"] and stats["tags"]


def test_mood_stats_for_companion_tool():
    eid = db.save_entry("journal", "user", "stressed")
    db.save_mood(eid, -0.5, 0.8, "stress", ["busy"], "{}")
    stats = db.get_mood_stats_for_agent()
    assert stats["category_counts"].get("stress", 0) >= 1


def test_archive_day_detection_and_summary():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    eid = db.save_entry("companion", "user", "had a rough day")
    conn = __import__("sqlite3").connect(str(db._DB_PATH))
    conn.execute(
        "UPDATE journal_entries SET created_at=? WHERE id=?",
        (f"{yesterday}T12:00:00Z", eid),
    )
    conn.commit()
    conn.close()

    assert yesterday in db.get_days_needing_summary()
    assert db.get_day_chat_messages(yesterday) == ["had a rough day"]

    db.save_summary(yesterday, "You reflected on a lot.")
    assert yesterday not in db.get_days_needing_summary()
