"""
Integration tests for Within API endpoints.

Uses a real SQLite database (temp dir) and real Cactus FFI / Gemma 4.
No mocks. Each test class gets a fresh isolated DB so tests don't interfere.

Run:
    pytest test/test_api.py -v
"""

import json
from pathlib import Path

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient, ASGITransport

# ── per-test isolated DB + data dirs ─────────────────────────────────────────

@pytest_asyncio.fixture
async def client(tmp_path):
    """
    Each test gets a completely fresh SQLite DB and empty data dirs.
    Overrides module-level paths so tests never share state.
    """
    import app.db as db_mod
    import app.main as main_mod

    audio_dir = tmp_path / "audio"
    image_dir = tmp_path / "images"
    audio_dir.mkdir()
    image_dir.mkdir()

    db_mod._DB_PATH = tmp_path / "journal.db"
    main_mod.AUDIO_DIR = audio_dir
    main_mod.IMAGE_DIR = image_dir

    db_mod.init_db()

    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── small helpers ─────────────────────────────────────────────────────────────

def _small_png() -> bytes:
    """Minimal valid 1×1 white PNG (67 bytes)."""
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )


def _small_webm() -> bytes:
    """
    A minimal valid WebM container (~9 bytes).
    ffmpeg will reject it; tests that call /api/companion/voice will see a 503.
    For /api/voice (raw storage) it is accepted fine.
    """
    return bytes([
        0x1A, 0x45, 0xDF, 0xA3,  # EBML ID
        0x84,                    # size = 4
        0x42, 0x86, 0x81, 0x01,  # EBMLVersion = 1
    ])


def _collect_sse(text: str) -> list[dict]:
    """Parse SSE response body into a list of decoded JSON payloads."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/journal
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_journal_saves_entry(client):
    r = await client.post("/api/journal", json={"text": "I feel calm today."})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_journal_rejects_empty(client):
    r = await client.post("/api/journal", json={"text": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_journal_entry_appears_in_history(client):
    await client.post("/api/journal", json={"text": "Feeling anxious about tomorrow."})
    r = await client.get("/api/history")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert any("anxious" in (e.get("content") or "") for e in entries)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/companion/chat  (real Gemma 4)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_companion_chat_returns_tokens(client):
    r = await client.post("/api/companion/chat", json={"message": "Hello, how are you?"})
    assert r.status_code == 200
    events = _collect_sse(r.text)
    tokens = [e["token"] for e in events if "token" in e]
    done_events = [e for e in events if e.get("done")]
    assert len(tokens) > 0, "Expected at least one token from Gemma 4"
    assert len(done_events) == 1
    assert "session_id" in done_events[0]


@pytest.mark.asyncio
async def test_companion_chat_persists_session(client):
    r1 = await client.post("/api/companion/chat", json={"message": "My name is Alex."})
    sid = [e for e in _collect_sse(r1.text) if e.get("done")][0]["session_id"]

    r2 = await client.post("/api/companion/chat", json={"message": "What is my name?", "session_id": sid})
    events = _collect_sse(r2.text)
    full_reply = "".join(e.get("token", "") for e in events)
    assert "alex" in full_reply.lower(), "Model should recall the name from session history"


@pytest.mark.asyncio
async def test_companion_chat_rejects_empty(client):
    r = await client.post("/api/companion/chat", json={"message": ""})
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/voice  (journal raw audio storage)
# ─────────────────────────────────────────────────────────────────────────────

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
async def test_voice_journal_appears_in_history(client):
    await client.post(
        "/api/voice",
        files={"file": ("audio.webm", _small_webm(), "audio/webm")},
        data={"mode": "journal"},
    )
    r = await client.get("/api/history")
    entries = r.json()["entries"]
    assert any(e.get("source") == "voice" for e in entries)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/companion/voice  (native Gemma 4 audio)
# Note: _small_webm() is not a valid audio stream, so ffmpeg will fail → 503.
# Test that the error path is handled cleanly (no crash, correct status).
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_companion_voice_bad_audio_returns_503(client):
    r = await client.post(
        "/api/companion/voice",
        files={"file": ("audio.webm", _small_webm(), "audio/webm")},
    )
    assert r.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/image
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_image_upload_saves(client):
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
async def test_image_upload_rejects_wrong_mime(client):
    r = await client.post(
        "/api/image",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        data={"mode": "journal"},
    )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_image_upload_rejects_too_large(client):
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
async def test_image_file_404_unknown_id(client):
    r = await client.get("/api/image/999999/file")
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/history
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_timeline_empty(client):
    r = await client.get("/api/history")
    assert r.status_code == 200
    assert r.json()["entries"] == []


@pytest.mark.asyncio
async def test_history_timeline_returns_entry(client):
    await client.post("/api/journal", json={"text": "A quiet evening."})
    r = await client.get("/api/history")
    entries = r.json()["entries"]
    assert len(entries) >= 1
    e = entries[0]
    assert e["mode"] == "journal"
    assert e["source"] == "text"
    assert e["content"] == "A quiet evening."


@pytest.mark.asyncio
async def test_history_calendar_view(client):
    await client.post("/api/journal", json={"text": "Calendar test."})
    r = await client.get("/api/history?view=calendar")
    assert r.status_code == 200
    data = r.json()["entries"]
    assert isinstance(data, list)
    if data:
        assert "day" in data[0]
        assert "count" in data[0]


@pytest.mark.asyncio
async def test_history_day_filter(client):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await client.post("/api/journal", json={"text": "Day filter test."})
    r = await client.get(f"/api/history?day={today}")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert any("Day filter test" in (e.get("content") or "") for e in entries)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_empty(client):
    r = await client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "daily" in body
    assert "tags" in body
    assert "categories" in body


@pytest.mark.asyncio
async def test_stats_after_companion_chat(client):
    await client.post("/api/companion/chat", json={"message": "I am feeling really stressed today."})
    r = await client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["daily"], list)
    assert isinstance(body["tags"], list)


# ─────────────────────────────────────────────────────────────────────────────
# GET /  (page render)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_page_renders(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "Within" in r.text
