"""
Feature tests for FastAPI endpoints. Stubs Cactus FFI so no model required.
Tests cover the observable contract of each endpoint: status codes, response
shape, DB side-effects, and SSE event structure.
"""

import asyncio
import base64
import json
from pathlib import Path

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient, ASGITransport

import app.db as db_mod
import app.engine as engine_mod
import app.emotion as emotion_mod
import app.reflect as reflect_mod


# ── fixtures ──────────────────────────────────────────────────────────────────

def _small_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )

def _small_webm() -> bytes:
    return bytes([0x1A, 0x45, 0xDF, 0xA3, 0x84, 0x42, 0x86, 0x81, 0x01])


def _collect_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh DB, stubbed FFI, isolated data dirs."""
    audio_dir = tmp_path / "audio"
    image_dir = tmp_path / "images"
    audio_dir.mkdir()
    image_dir.mkdir()

    monkeypatch.setattr(db_mod, "_DB_PATH", tmp_path / "journal.db")

    # Patch engine before importing app.main to avoid model load
    def _fake_run_complete(messages, options, pcm_data=None):
        return {"reply": "stub reply from model"}

    monkeypatch.setattr(engine_mod, "_run_complete", _fake_run_complete)

    # Stub emotion extraction so _tag_entry doesn't crash
    monkeypatch.setattr(
        emotion_mod, "extract_emotion_sync",
        lambda text: {"valence": 0.3, "intensity": 0.5, "category": "positive", "sub_tags": ["content"], "raw": "{}"}
    )

    # Stub reflect_open_sync
    monkeypatch.setattr(
        reflect_mod, "reflect_open_sync",
        lambda snapshots: {
            "greeting": "Good to see you.",
            "topics": [
                {"label": "Stress", "question": "What's been stressing you?", "rag_query": "stress", "type": "pattern"},
                {"label": "Just talk", "question": "Just talk", "rag_query": "", "type": "just_chat"},
            ]
        }
    )

    # Stub reflect_agent_sync
    def _fake_agent(topic_label, topic_question, rag_query, history, token_queue):
        token_queue.put("stub ")
        token_queue.put("agent ")
        token_queue.put("reply")
        token_queue.put(None)
        return {"reply": "stub agent reply"}

    monkeypatch.setattr(reflect_mod, "reflect_agent_sync", _fake_agent)

    # Stub chat_stream_sync
    import app.chat as chat_mod

    def _fake_chat_stream(text, history, token_queue, pcm_data=None):
        token_queue.put("hello ")
        token_queue.put("world")
        token_queue.put(None)
        return {"reply": "hello world"}

    monkeypatch.setattr(chat_mod, "chat_stream_sync", _fake_chat_stream)

    import importlib
    import app.main as main_mod
    main_mod.AUDIO_DIR = audio_dir
    main_mod.IMAGE_DIR = image_dir

    db_mod.init_db()

    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── POST /api/journal ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_journal_save(client):
    r = await client.post("/api/journal", json={"text": "Feeling calm today."})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_journal_empty_text_rejected(client):
    r = await client.post("/api/journal", json={"text": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_journal_entry_in_history(client):
    await client.post("/api/journal", json={"text": "A rainy afternoon."})
    r = await client.get("/api/history")
    entries = r.json()["entries"]
    assert any("rainy" in (e.get("content") or "") for e in entries)


# ── POST /api/chat/stream ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_stream_tokens(client):
    r = await client.post("/api/chat/stream", json={"text": "Hello"})
    assert r.status_code == 200
    events = _collect_sse(r.text)
    tokens = [e["token"] for e in events if "token" in e]
    assert len(tokens) > 0


@pytest.mark.asyncio
async def test_chat_stream_done_payload(client):
    r = await client.post("/api/chat/stream", json={"text": "Hi there"})
    events = _collect_sse(r.text)
    done = [e for e in events if e.get("done")]
    assert len(done) == 1
    assert "session_id" in done[0]


@pytest.mark.asyncio
async def test_chat_stream_saves_both_roles(client, tmp_path):
    r = await client.post("/api/chat/stream", json={"text": "test message"})
    sid = [e for e in _collect_sse(r.text) if e.get("done")][0]["session_id"]

    messages = db_mod.get_session_messages(sid)
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_chat_stream_session_continuity(client):
    r1 = await client.post("/api/chat/stream", json={"text": "first message"})
    sid = [e for e in _collect_sse(r1.text) if e.get("done")][0]["session_id"]

    r2 = await client.post("/api/chat/stream", json={"text": "second message", "session_id": sid})
    assert r2.status_code == 200
    # Both turns should be in session history
    messages = db_mod.get_session_messages(sid)
    assert len(messages) >= 2


# ── POST /api/voice (raw storage) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_journal_saves(client):
    r = await client.post(
        "/api/voice",
        files={"file": ("audio.webm", _small_webm(), "audio/webm")},
        data={"mode": "journal"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert isinstance(body["entry_id"], int)
    assert isinstance(body["audio_id"], int)


@pytest.mark.asyncio
async def test_voice_appears_in_history(client):
    await client.post(
        "/api/voice",
        files={"file": ("audio.webm", _small_webm(), "audio/webm")},
        data={"mode": "journal"},
    )
    r = await client.get("/api/history")
    entries = r.json()["entries"]
    assert any(e.get("source") == "voice" for e in entries)


# ── POST /api/image ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_image_upload(client):
    r = await client.post(
        "/api/image",
        files={"file": ("photo.png", _small_png(), "image/png")},
        data={"mode": "journal"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert isinstance(body["entry_id"], int)
    assert isinstance(body["image_id"], int)


@pytest.mark.asyncio
async def test_image_rejects_wrong_mime(client):
    r = await client.post(
        "/api/image",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        data={"mode": "journal"},
    )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_image_rejects_too_large(client):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = await client.post(
        "/api/image",
        files={"file": ("big.jpg", big, "image/jpeg")},
        data={"mode": "journal"},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_image_file_served(client):
    up = await client.post(
        "/api/image",
        files={"file": ("photo.png", _small_png(), "image/png")},
        data={"mode": "journal"},
    )
    image_id = up.json()["image_id"]
    r = await client.get(f"/api/image/{image_id}/file")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == _small_png()


@pytest.mark.asyncio
async def test_image_404_unknown(client):
    r = await client.get("/api/image/999999/file")
    assert r.status_code == 404


# ── GET /api/reflect/open ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflect_open_no_entries(client):
    r = await client.get("/api/reflect/open")
    assert r.status_code == 200
    events = _collect_sse(r.text)
    result_events = [e for e in events if "result" in e]
    assert len(result_events) == 1
    payload = result_events[0]["result"]
    assert "greeting" in payload
    assert "topics" in payload


@pytest.mark.asyncio
async def test_reflect_open_step_events(client):
    r = await client.get("/api/reflect/open")
    events = _collect_sse(r.text)
    step_events = [e for e in events if "step" in e]
    assert len(step_events) >= 1


@pytest.mark.asyncio
async def test_reflect_open_topics_always_has_just_chat(client):
    # Seed some entries so reflect_open_sync is called (not the empty-DB short-circuit)
    eid = db_mod.save_entry("journal", "user", "stressed about work")
    db_mod.save_mood(eid, -0.5, 0.7, "stress", ["busy"], "{}")

    r = await client.get("/api/reflect/open")
    events = _collect_sse(r.text)
    result_events = [e for e in events if "result" in e]
    topics = result_events[0]["result"]["topics"]
    types = [t["type"] for t in topics]
    assert "just_chat" in types


# ── POST /api/reflect/chat ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflect_chat_just_chat_branch(client):
    body = {
        "topic_label": "Just talk",
        "topic_question": "Whatever's on your mind",
        "rag_query": "",
        "topic_type": "just_chat",
        "history": [],
        "user_message": "I just want to chat",
    }
    r = await client.post("/api/reflect/chat", json=body)
    assert r.status_code == 200
    events = _collect_sse(r.text)
    tool_events = [e for e in events if "tool_call" in e]
    assert len(tool_events) == 0  # just_chat should never emit tool_call


@pytest.mark.asyncio
async def test_reflect_chat_just_chat_saves_chat_mode(client):
    body = {
        "topic_label": "Just talk",
        "topic_question": "Free chat",
        "rag_query": "",
        "topic_type": "just_chat",
        "history": [],
        "user_message": "just chatting",
    }
    await client.post("/api/reflect/chat", json=body)
    # just_chat saves as mode='chat' with a session_id
    rows = db_mod.get_history("timeline")
    modes = [r["mode"] for r in rows]
    assert "chat" in modes


@pytest.mark.asyncio
async def test_reflect_chat_agent_branch_done_payload(client):
    body = {
        "topic_label": "Stress",
        "topic_question": "What's been stressing you?",
        "rag_query": "stress",
        "topic_type": "pattern",
        "history": [],
        "user_message": "I've been really stressed at work",
    }
    r = await client.post("/api/reflect/chat", json=body)
    assert r.status_code == 200
    events = _collect_sse(r.text)
    done = [e for e in events if e.get("done")]
    assert len(done) == 1
    assert "reply" in done[0]


@pytest.mark.asyncio
async def test_reflect_chat_agent_saves_reflect_mode(client):
    body = {
        "topic_label": "Stress",
        "topic_question": "What's stressing you?",
        "rag_query": "stress",
        "topic_type": "pattern",
        "history": [],
        "user_message": "work is overwhelming",
    }
    await client.post("/api/reflect/chat", json=body)
    # save_entry for reflect is fire-and-forget via create_task; give it a tick
    await asyncio.sleep(0.1)
    rows = db_mod.get_history("timeline")
    modes = [r["mode"] for r in rows]
    assert "reflect" in modes


# ── GET /api/history ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_empty(client):
    r = await client.get("/api/history")
    assert r.status_code == 200
    assert r.json()["entries"] == []


@pytest.mark.asyncio
async def test_history_timeline_shape(client):
    await client.post("/api/journal", json={"text": "shape test"})
    r = await client.get("/api/history")
    entry = r.json()["entries"][0]
    for field in ("id", "created_at", "mode", "content", "source"):
        assert field in entry


@pytest.mark.asyncio
async def test_history_calendar_shape(client):
    await client.post("/api/journal", json={"text": "cal test"})
    r = await client.get("/api/history?view=calendar")
    data = r.json()["entries"]
    assert isinstance(data, list)
    if data:
        assert "day" in data[0]
        assert "count" in data[0]
        assert "categories" in data[0]


@pytest.mark.asyncio
async def test_history_day_filter(client):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await client.post("/api/journal", json={"text": "day filter entry"})
    r = await client.get(f"/api/history?day={today}")
    entries = r.json()["entries"]
    assert any("day filter entry" in (e.get("content") or "") for e in entries)


# ── GET /api/stats ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_shape(client):
    r = await client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "daily" in body
    assert "tags" in body
    assert "categories" in body


# ── GET /api/insights/narrative ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insights_narrative_returns_string(client, monkeypatch):
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "insight_narrative_sync", lambda stats: "You had a thoughtful week.")
    main_mod._narrative_cache["text"] = ""
    main_mod._narrative_cache["expires"] = 0.0

    r = await client.get("/api/insights/narrative")
    assert r.status_code == 200
    assert "narrative" in r.json()


@pytest.mark.asyncio
async def test_insights_narrative_cached(client, monkeypatch):
    call_count = {"n": 0}

    def _counting_narrative(stats):
        call_count["n"] += 1
        return "cached narrative"

    import app.main as main_mod
    # main.py imports insight_narrative_sync by name, so patch on main_mod
    monkeypatch.setattr(main_mod, "insight_narrative_sync", _counting_narrative)
    main_mod._narrative_cache["text"] = ""
    main_mod._narrative_cache["expires"] = 0.0

    await client.get("/api/insights/narrative")
    await client.get("/api/insights/narrative")
    assert call_count["n"] == 1


# ── POST /api/warmup ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_warmup_returns_ready(client, monkeypatch):
    monkeypatch.setattr(engine_mod, "warmup_sync", lambda: None)
    r = await client.post("/api/warmup")
    assert r.status_code == 200
    assert r.json()["ready"] is True
