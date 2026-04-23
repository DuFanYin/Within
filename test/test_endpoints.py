"""
Stubbed endpoint tests. Covers what integration tests cannot:
- SSE event structure (tool_call sentinel, done payload shape)
- DB side-effects that require mode inspection (companion mode saved)
- Cache logic (narrative cache)
- Reflect/open SSE structure (uses stub, no model needed)

Everything else (status codes, basic saves, history/stats shape) is covered
by test_api.py integration tests and not repeated here.
"""

import asyncio
import base64
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

import app.db as db_mod
import app.engine as engine_mod
import app.emotion as emotion_mod
import app.reflect as reflect_mod
import app.agent as agent_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _collect_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _small_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    image_dir = tmp_path / "images"
    audio_dir.mkdir()
    image_dir.mkdir()

    monkeypatch.setattr(db_mod, "_DB_PATH", tmp_path / "journal.db")
    monkeypatch.setattr(engine_mod, "_run_complete", lambda msgs, opts, pcm=None: {"reply": "stub"})
    monkeypatch.setattr(
        emotion_mod, "extract_emotion_sync",
        lambda text: {"valence": 0.3, "intensity": 0.5, "category": "positive", "sub_tags": ["content"], "raw": "{}"}
    )
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

    def _fake_agent(message, history, mood_snapshots, token_queue, pcm_data=None):
        token_queue.put("stub ")
        token_queue.put("reply")
        token_queue.put(None)
        return {"reply": "stub reply"}

    monkeypatch.setattr(agent_mod, "companion_agent_sync", _fake_agent)

    import app.main as main_mod
    main_mod.AUDIO_DIR = audio_dir
    main_mod.IMAGE_DIR = image_dir
    main_mod.companion_agent_sync = _fake_agent

    db_mod.init_db()

    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── companion chat: DB side-effects ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_companion_chat_saves_companion_mode(client):
    r = await client.post("/api/companion/chat", json={"message": "test"})
    sid = [e for e in _collect_sse(r.text) if e.get("done")][0]["session_id"]
    await asyncio.sleep(0.1)
    modes = [row["mode"] for row in db_mod.get_history("timeline")]
    assert "companion" in modes


@pytest.mark.asyncio
async def test_companion_chat_saves_both_roles(client):
    r = await client.post("/api/companion/chat", json={"message": "test"})
    sid = [e for e in _collect_sse(r.text) if e.get("done")][0]["session_id"]
    messages = db_mod.get_session_messages(sid)
    roles = {m["role"] for m in messages}
    assert roles == {"user", "assistant"}


@pytest.mark.asyncio
async def test_companion_chat_session_continuity(client):
    r1 = await client.post("/api/companion/chat", json={"message": "first"})
    sid = [e for e in _collect_sse(r1.text) if e.get("done")][0]["session_id"]
    await client.post("/api/companion/chat", json={"message": "second", "session_id": sid})
    assert len(db_mod.get_session_messages(sid)) >= 4  # 2 turns × 2 roles


# ── companion chat: SSE event structure ──────────────────────────────────────

@pytest.mark.asyncio
async def test_companion_chat_tool_call_event(client, monkeypatch):
    import app.main as main_mod

    def _agent_with_tool(message, history, mood_snapshots, token_queue, pcm_data=None):
        token_queue.put("\x00TOOL:🔍 Searching…\x00")
        token_queue.put("result")
        token_queue.put(None)
        return {"reply": "result"}

    monkeypatch.setattr(main_mod, "companion_agent_sync", _agent_with_tool)

    r = await client.post("/api/companion/chat", json={"message": "search"})
    events = _collect_sse(r.text)
    tool_events = [e for e in events if "tool_call" in e]
    assert len(tool_events) == 1
    assert "Searching" in tool_events[0]["tool_call"]


# ── reflect/open: SSE structure + topics contract ────────────────────────────

@pytest.mark.asyncio
async def test_reflect_open_sse_structure(client):
    r = await client.get("/api/reflect/open")
    events = _collect_sse(r.text)
    assert any("step" in e for e in events)
    result_events = [e for e in events if "result" in e]
    assert len(result_events) == 1
    payload = result_events[0]["result"]
    assert "greeting" in payload and "topics" in payload


@pytest.mark.asyncio
async def test_reflect_open_topics_has_just_chat(client):
    eid = db_mod.save_entry("journal", "user", "stressed about work")
    db_mod.save_mood(eid, -0.5, 0.7, "stress", ["busy"], "{}")
    r = await client.get("/api/reflect/open")
    events = _collect_sse(r.text)
    topics = [e for e in events if "result" in e][0]["result"]["topics"]
    assert any(t["type"] == "just_chat" for t in topics)


# ── insights narrative: cache logic ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_insights_narrative_cached(client, monkeypatch):
    call_count = {"n": 0}

    def _counting(stats):
        call_count["n"] += 1
        return "narrative"

    import app.main as main_mod
    monkeypatch.setattr(main_mod, "insight_narrative_sync", _counting)
    main_mod._narrative_cache["text"] = ""
    main_mod._narrative_cache["expires"] = 0.0

    await client.get("/api/insights/narrative")
    await client.get("/api/insights/narrative")
    assert call_count["n"] == 1
