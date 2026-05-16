"""HTTP flows: journal, history, insights, background jobs, companion SSE shape."""

import sqlite3

import pytest

import app.agent as agent_mod
import app.db as db_mod
import app.main as main_mod

from support import collect_sse, small_png, small_webm


@pytest.mark.asyncio
async def test_journal_voice_image_and_history(client):
    await client.post("/api/journal", json={"text": "A quiet evening."})
    assert (await client.post(
        "/api/voice",
        files={"file": ("audio.webm", small_webm(), "audio/webm")},
        data={"mode": "journal"},
    )).status_code == 200
    assert (await client.post(
        "/api/image",
        files={"file": ("photo.png", small_png(), "image/png")},
        data={"mode": "journal", "note": "park"},
    )).status_code == 200

    entries = (await client.get("/api/history")).json()["entries"]
    assert any(e.get("mode") == "journal" for e in entries)


@pytest.mark.asyncio
async def test_stats_and_insights_narrative(client, monkeypatch):
    eid = (await client.post("/api/journal", json={"text": "Feeling reflective."})).json()["id"]
    db_mod.save_mood(eid, 0.2, 0.5, "positive", ["calm"], "{}")

    stats = await client.get("/api/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert "daily" in body and "tags" in body

    monkeypatch.setattr(main_mod, "insight_narrative_sync", lambda s: "Weekly reflection.")
    main_mod._narrative_cache["text"] = ""
    main_mod._narrative_cache["expires"] = 0.0
    assert (await client.get("/api/insights/narrative")).json()["narrative"]
    assert (await client.get("/api/insights/narrative")).json()["narrative"] == "Weekly reflection."


@pytest.mark.asyncio
async def test_background_audio_pipeline(client, monkeypatch):
    monkeypatch.setattr(main_mod, "transcribe_bytes_sync", lambda _b, _s: "hello from voice")
    monkeypatch.setattr(main_mod, "tone_summary_sync", lambda t: "calm")
    monkeypatch.setattr(
        main_mod, "extract_emotion_sync",
        lambda t: {
            "valence": 0.2, "intensity": 0.4,
            "category": "positive", "sub_tags": ["content"], "raw": "{}",
        },
    )

    entry_id = (await client.post(
        "/api/voice",
        files={"file": ("audio.webm", small_webm(), "audio/webm")},
        data={"mode": "journal"},
    )).json()["entry_id"]

    assert (await client.post("/api/dev/process-pending-audio")).json()["processed"] >= 1

    conn = sqlite3.connect(str(db_mod._DB_PATH))
    content = conn.execute(
        "SELECT content FROM journal_entries WHERE id=?", (entry_id,)
    ).fetchone()[0]
    conn.close()
    assert content == "hello from voice"


@pytest.mark.asyncio
async def test_background_image_pipeline(client, monkeypatch):
    monkeypatch.setattr(main_mod, "image_caption_sync", lambda path, mime: "sunny day")

    image_id = (await client.post(
        "/api/image",
        files={"file": ("photo.png", small_png(), "image/png")},
        data={"mode": "journal"},
    )).json()["image_id"]

    assert (await client.post("/api/dev/process-pending-images")).json()["processed"] >= 1

    conn = sqlite3.connect(str(db_mod._DB_PATH))
    caption = conn.execute(
        "SELECT caption FROM image_files WHERE id=?", (image_id,)
    ).fetchone()[0]
    conn.close()
    assert caption == "sunny day"


@pytest.mark.asyncio
async def test_background_archive_pipeline(client, monkeypatch):
    from datetime import date, timedelta

    monkeypatch.setattr(main_mod, "summarize_sync", lambda day, msgs: f"Summary for {day}")
    old = (date.today() - timedelta(days=2)).isoformat()
    eid = db_mod.save_entry("companion", "user", "old chat", session_id="s1")
    conn = sqlite3.connect(str(db_mod._DB_PATH))
    conn.execute(
        "UPDATE journal_entries SET created_at=? WHERE id=?",
        (f"{old} 12:00:00", eid),
    )
    conn.commit()
    conn.close()

    body = (await client.post("/api/dev/archive-summaries")).json()
    assert body["archived"] >= 1 and old in body["days"]


@pytest.mark.asyncio
async def test_companion_tool_sse_event(client, monkeypatch):
    def agent_with_tool(message, history, mood_snapshots, token_queue, pcm_data=None, image_bytes=None, image_mime=None):
        token_queue.put("\x00TOOL:🔍 Searching…\x00")
        token_queue.put("ok")
        token_queue.put(None)
        return {"reply": "ok"}

    monkeypatch.setattr(agent_mod, "companion_agent_sync", agent_with_tool)
    r = await client.post("/api/companion/chat", json={"message": "search my entries"})
    assert any("tool_call" in e for e in collect_sse(r.text))
