"""
Tests for app/db.py — schema, reads and writes.
All tests use an isolated temp DB via the isolated_db fixture.
"""

import json
import sqlite3
from pathlib import Path

import pytest
import app.db as db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()


# ── schema ────────────────────────────────────────────────────────────────────

def test_all_tables_created(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "fresh.db")
    db.init_db()
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"journal_entries", "mood_snapshots", "audio_files", "image_files"} <= tables


def test_all_modes_accepted():
    for mode in ("chat", "journal", "reflect", "companion"):
        eid = db.save_entry(mode, "user", f"entry for {mode}")
        assert eid > 0


# ── entry writes / reads ──────────────────────────────────────────────────────

def test_save_entry_returns_int():
    eid = db.save_entry("journal", "user", "hello")
    assert isinstance(eid, int) and eid > 0


def test_save_mood_links_entry():
    eid = db.save_entry("journal", "user", "calm day")
    db.save_mood(eid, 0.5, 0.4, "positive", ["happy"], '{"valence":0.5}')

    conn = sqlite3.connect(str(db._DB_PATH))
    row = conn.execute("SELECT entry_id, category FROM mood_snapshots WHERE entry_id=?", (eid,)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == eid
    assert row[1] == "positive"


def test_get_session_messages_order():
    sid = "sess-order"
    db.save_entry("chat", "user", "first", session_id=sid)
    db.save_entry("chat", "assistant", "second", session_id=sid)
    db.save_entry("chat", "user", "third", session_id=sid)
    msgs = db.get_session_messages(sid)
    assert [m["content"] for m in msgs] == ["first", "second", "third"]


def test_get_session_messages_isolation():
    db.save_entry("chat", "user", "session A msg", session_id="sessA")
    db.save_entry("chat", "user", "session B msg", session_id="sessB")
    msgs = db.get_session_messages("sessA")
    assert all(m["content"] == "session A msg" for m in msgs)
    assert len(msgs) == 1


def test_get_session_messages_limit():
    sid = "sess-limit"
    for i in range(25):
        db.save_entry("chat", "user", f"msg {i}", session_id=sid)
    msgs = db.get_session_messages(sid, limit=20)
    assert len(msgs) == 20


def test_get_corpus_entries_incremental():
    e1 = db.save_entry("journal", "user", "entry one")
    e2 = db.save_entry("journal", "user", "entry two")
    e3 = db.save_entry("journal", "user", "entry three")

    entries = db.get_corpus_entries(since_id=e1)
    ids = [e["id"] for e in entries]
    assert e1 not in ids
    assert e2 in ids and e3 in ids


def test_get_corpus_entries_excludes_assistant():
    db.save_entry("chat", "user", "user msg")
    db.save_entry("chat", "assistant", "assistant reply")
    entries = db.get_corpus_entries(since_id=0)
    assert all(e["content"] != "assistant reply" for e in entries)


def test_get_recent_mood_window():
    eid = db.save_entry("journal", "user", "recent entry")
    db.save_mood(eid, 0.3, 0.5, "positive", ["content"], "{}")

    conn = sqlite3.connect(str(db._DB_PATH))
    conn.execute(
        "UPDATE mood_snapshots SET created_at = datetime('now', '-20 days') WHERE entry_id=?", (eid,)
    )
    conn.commit()
    conn.close()

    rows = db.get_recent_mood(days=14)
    assert all(r["category"] != "positive" for r in rows)


def test_get_last_reflect_summary_returns_none_when_empty():
    assert db.get_last_reflect_summary() is None


def test_get_last_reflect_summary_returns_last():
    db.save_entry("reflect", "user", "I talked about work stress")
    result = db.get_last_reflect_summary()
    assert result is not None
    assert "work stress" in result["content"]


def test_get_last_reflect_summary_includes_companion_mode():
    db.save_entry("companion", "user", "companion session entry")
    result = db.get_last_reflect_summary()
    assert result is not None
    assert "companion session entry" in result["content"]


def test_get_session_messages_companion_mode():
    sid = "comp-sess"
    db.save_entry("companion", "user", "hello companion", session_id=sid)
    db.save_entry("companion", "assistant", "hi there", session_id=sid)
    msgs = db.get_session_messages(sid)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "hello companion"


# ── audio records ─────────────────────────────────────────────────────────────

def test_save_audio_file_returns_id():
    aid = db.save_audio_file("voice.webm", 12345, 3.5)
    assert isinstance(aid, int) and aid > 0


def test_update_audio_transcript():
    aid = db.save_audio_file("voice.webm", 100, None)
    db.update_audio_transcript(aid, "I went for a walk today.", "The speaker sounds calm and measured.")

    conn = sqlite3.connect(str(db._DB_PATH))
    row = conn.execute("SELECT transcript, tone_summary FROM audio_files WHERE id=?", (aid,)).fetchone()
    conn.close()
    assert row[0] == "I went for a walk today."
    assert row[1] == "The speaker sounds calm and measured."


def test_get_pending_audio_entries():
    aid = db.save_audio_file("pending.webm", 100, None)
    eid = db.save_entry("journal", "user", "", source="voice", audio_id=aid)

    pending = db.get_pending_audio_entries()
    assert any(p["entry_id"] == eid and p["audio_id"] == aid for p in pending)


def test_get_pending_audio_entries_excludes_transcribed():
    aid = db.save_audio_file("done.webm", 100, None)
    db.save_entry("journal", "user", "hello", source="voice", audio_id=aid)
    db.update_audio_transcript(aid, "hello", "calm")

    pending = db.get_pending_audio_entries()
    assert all(p["audio_id"] != aid for p in pending)


# ── image records ─────────────────────────────────────────────────────────────

def test_save_image_file_returns_id():
    iid = db.save_image_file("photo.png", "image/png", 50000)
    assert isinstance(iid, int) and iid > 0


def test_update_image_caption():
    iid = db.save_image_file("photo.jpg", "image/jpeg", 20000)
    db.update_image_caption(iid, "A warm sunset over the hills.")

    conn = sqlite3.connect(str(db._DB_PATH))
    row = conn.execute("SELECT caption FROM image_files WHERE id=?", (iid,)).fetchone()
    conn.close()
    assert row[0] == "A warm sunset over the hills."


def test_get_pending_image_entries():
    iid = db.save_image_file("nocap.jpg", "image/jpeg", 1000)
    eid = db.save_entry("journal", "user", "", source="image", image_id=iid)

    pending = db.get_pending_image_entries()
    assert any(p["entry_id"] == eid and p["image_id"] == iid for p in pending)


def test_get_pending_image_entries_excludes_captioned():
    iid = db.save_image_file("captioned.jpg", "image/jpeg", 1000)
    db.save_entry("journal", "user", "", source="image", image_id=iid)
    db.update_image_caption(iid, "a photo of leaves")

    pending = db.get_pending_image_entries()
    assert all(p["image_id"] != iid for p in pending)


# ── stats & history ───────────────────────────────────────────────────────────

def test_get_stats_empty():
    result = db.get_stats()
    assert result == {"daily": [], "tags": [], "categories": []}


def test_get_stats_aggregates_same_day():
    e1 = db.save_entry("journal", "user", "morning")
    e2 = db.save_entry("journal", "user", "evening")
    db.save_mood(e1, 0.4, 0.5, "positive", ["happy"], "{}")
    db.save_mood(e2, 0.6, 0.7, "positive", ["content"], "{}")

    result = db.get_stats()
    assert len(result["daily"]) == 1
    assert abs(result["daily"][0]["valence"] - 0.5) < 0.01


def test_get_stats_tags_flattened():
    e1 = db.save_entry("journal", "user", "busy day")
    db.save_mood(e1, -0.3, 0.7, "stress", ["busy", "overwhelmed"], "{}")

    result = db.get_stats()
    tag_names = [t["tag"] for t in result["tags"]]
    assert "busy" in tag_names and "overwhelmed" in tag_names


def test_get_history_timeline_shape():
    db.save_entry("journal", "user", "timeline entry")
    rows = db.get_history("timeline")
    assert len(rows) >= 1
    row = rows[0]
    assert "id" in row and "created_at" in row and "mode" in row and "content" in row


def test_get_history_calendar_groups_by_day():
    db.save_entry("journal", "user", "cal entry")
    rows = db.get_history("calendar")
    assert len(rows) >= 1
    assert "day" in rows[0] and "count" in rows[0] and "categories" in rows[0]


def test_get_history_day_filter():
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db.save_entry("journal", "user", "today entry")
    rows = db.get_history("timeline", day=today)
    assert any("today entry" in r["content"] for r in rows)


def test_get_mood_stats_for_agent_empty():
    result = db.get_mood_stats_for_agent()
    assert "category_counts" in result
    assert "top_tags" in result
    assert "avg_valence" in result
    assert "total_entries" in result
    assert result["total_entries"] == 0


def test_get_mood_stats_for_agent_counts():
    eid = db.save_entry("journal", "user", "stressed")
    db.save_mood(eid, -0.5, 0.8, "stress", ["busy", "drained"], "{}")
    result = db.get_mood_stats_for_agent()
    assert result["category_counts"].get("stress", 0) >= 1
    assert result["total_entries"] >= 1


# ── daily summary archiver ────────────────────────────────────────────────────

def _set_entry_day(entry_id: int, day: str) -> None:
    conn = sqlite3.connect(str(db._DB_PATH))
    conn.execute(
        "UPDATE journal_entries SET created_at=? WHERE id=?",
        (f"{day}T15:00:00Z", entry_id),
    )
    conn.commit()
    conn.close()


def test_get_days_needing_summary_includes_companion():
    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    eid = db.save_entry("companion", "user", "had a rough day")
    _set_entry_day(eid, yesterday)
    assert yesterday in db.get_days_needing_summary()


def test_get_days_needing_summary_includes_legacy_chat():
    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    eid = db.save_entry("chat", "user", "legacy chat message")
    _set_entry_day(eid, yesterday)
    assert yesterday in db.get_days_needing_summary()


def test_get_days_needing_summary_excludes_after_summary_saved():
    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    eid = db.save_entry("companion", "user", "content for summary")
    _set_entry_day(eid, yesterday)
    db.save_summary(yesterday, "You reflected on a lot.")
    assert yesterday not in db.get_days_needing_summary()


def test_get_days_needing_summary_skips_empty_content():
    from datetime import datetime, timedelta, timezone
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    eid = db.save_entry("companion", "user", "", source="voice")
    _set_entry_day(eid, yesterday)
    assert yesterday not in db.get_days_needing_summary()


def test_get_days_needing_summary_excludes_today():
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eid = db.save_entry("companion", "user", "still today")
    _set_entry_day(eid, today)
    assert today not in db.get_days_needing_summary()


def test_get_day_chat_messages_merges_modes():
    from datetime import datetime, timedelta, timezone
    day = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    e1 = db.save_entry("chat", "user", "older chat")
    e2 = db.save_entry("companion", "user", "newer companion")
    _set_entry_day(e1, day)
    _set_entry_day(e2, day)
    assert db.get_day_chat_messages(day) == ["older chat", "newer companion"]


def test_save_summary_uses_companion_mode():
    from datetime import datetime, timedelta, timezone
    day = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    db.save_summary(day, "End of day reflection.")
    conn = sqlite3.connect(str(db._DB_PATH))
    row = conn.execute(
        "SELECT mode, role, content FROM journal_entries WHERE role='summary'"
    ).fetchone()
    conn.close()
    assert row[0] == "companion"
    assert row[1] == "summary"
    assert row[2] == "End of day reflection."
