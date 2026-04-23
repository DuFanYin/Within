"""
Within — FastAPI backend.

Start from app root:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import queue
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .db import (
    init_db, save_entry, save_mood,
    save_audio_file, update_audio_transcript, update_entry_content, get_pending_audio_entries,
    get_recent_mood, get_last_reflect_summary,
    save_image_file, update_image_caption, get_pending_image_entries,
    get_session_messages, get_history, get_days_needing_summary, get_day_chat_messages,
    save_summary, get_corpus_entries, get_stats,
)
from .corpus import export_corpus_incremental, _corpus_cursor
from .agent import companion_agent_sync
from .emotion import extract_emotion_sync, summarize_sync, tone_summary_sync, image_caption_sync, insight_narrative_sync
from .reflect import reflect_open_sync
from .engine import warmup_sync
from .transcribe import transcribe_bytes_sync

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "data" / "audio"
IMAGE_DIR = ROOT / "data" / "images"

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _to_pcm_int16(audio_bytes: bytes, suffix: str = ".webm") -> bytes:
    """
    Convert any audio format (webm, mp4, ogg…) to PCM int16 mono 16 kHz
    using ffmpeg. Returns raw bytes suitable for cactus_complete pcm_data.
    Raises RuntimeError if ffmpeg is not found or conversion fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; install it to enable native audio chat")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(audio_bytes)
        src_path = src.name

    dst_path = src_path + ".pcm"
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", src_path,
                "-ar", "16000",
                "-ac", "1",
                "-f", "s16le",
                dst_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {result.stderr.decode()[-300:]}")
        return Path(dst_path).read_bytes()
    finally:
        Path(src_path).unlink(missing_ok=True)
        Path(dst_path).unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    asyncio.create_task(_warmup())
    asyncio.create_task(_sync_corpus())
    asyncio.create_task(_archiver_loop())
    asyncio.create_task(_audio_processor_loop())
    asyncio.create_task(_image_processor_loop())
    yield


app = FastAPI(title="Within", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


async def _warmup() -> None:
    try:
        await asyncio.to_thread(warmup_sync)
    except Exception:
        pass


async def _sync_corpus() -> None:
    """Export any new journal entries to corpus/ so RAG index is fresh."""
    try:
        import app.corpus as _corpus
        entries = await asyncio.to_thread(get_corpus_entries, _corpus._corpus_cursor)
        if entries:
            await asyncio.to_thread(export_corpus_incremental, entries)
    except Exception:
        pass


async def _archiver_loop() -> None:
    CHECK_INTERVAL = 300
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            days = await asyncio.to_thread(get_days_needing_summary)
            for day in days:
                asyncio.create_task(_archive_day(day))
        except Exception:
            pass


async def _audio_processor_loop() -> None:
    CHECK_INTERVAL = 120
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = await asyncio.to_thread(get_pending_audio_entries)
            for item in pending:
                asyncio.create_task(_process_audio_entry(item))
        except Exception:
            pass


async def _image_processor_loop() -> None:
    CHECK_INTERVAL = 120
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = await asyncio.to_thread(get_pending_image_entries)
            for item in pending:
                asyncio.create_task(_process_image_entry(item))
        except Exception:
            pass


async def _process_image_entry(item: dict) -> None:
    image_path = IMAGE_DIR / item["filename"]
    if not image_path.is_file():
        return
    try:
        caption = await asyncio.to_thread(
            image_caption_sync, str(image_path), item.get("mime_type", "image/jpeg")
        )
        if not caption:
            return
        await asyncio.to_thread(update_image_caption, item["image_id"], caption)
        asyncio.create_task(_sync_corpus())
    except Exception:
        pass


async def _process_audio_entry(item: dict) -> None:
    audio_path = AUDIO_DIR / item["filename"]
    if not audio_path.is_file():
        return
    try:
        audio_bytes = audio_path.read_bytes()
        suffix = "." + item["filename"].rsplit(".", 1)[-1]
        transcript = await asyncio.to_thread(transcribe_bytes_sync, audio_bytes, suffix)
        if not transcript:
            return
        tone = await asyncio.to_thread(tone_summary_sync, transcript)
        await asyncio.to_thread(update_audio_transcript, item["audio_id"], transcript, tone)
        await asyncio.to_thread(update_entry_content, item["entry_id"], transcript)
        asyncio.create_task(_tag_entry(item["entry_id"], transcript))
        asyncio.create_task(_sync_corpus())
    except Exception:
        pass


async def _archive_day(day: str) -> None:
    try:
        messages = await asyncio.to_thread(get_day_chat_messages, day)
        if not messages:
            return
        summary = await asyncio.to_thread(summarize_sync, day, messages)
        if summary:
            await asyncio.to_thread(save_summary, day, summary)
    except Exception:
        pass


# ── pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.post("/api/warmup")
async def warmup_endpoint() -> dict:
    """Called by the frontend banner; blocks until model is ready."""
    await asyncio.to_thread(warmup_sync)
    return {"ready": True}


# ── request models ────────────────────────────────────────────────────────────

class CompanionBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class JournalBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    source: str = "text"


# ── /api/companion/chat ───────────────────────────────────────────────────────

@app.post("/api/companion/chat")
async def companion_chat(body: CompanionBody) -> StreamingResponse:
    """SSE endpoint: companion agentic chat. Yields tokens then done event."""
    session_id = body.session_id or str(uuid.uuid4())
    history, snapshots = await asyncio.gather(
        asyncio.to_thread(get_session_messages, session_id),
        asyncio.to_thread(get_recent_mood, 7),
    )
    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None, companion_agent_sync,
            body.message, history, snapshots, token_q,
        )
        full_parts: list[str] = []
        while True:
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0)
                continue
            if token is None:
                break
            if token.startswith("\x00TOOL:") and token.endswith("\x00"):
                yield f"data: {json.dumps({'tool_call': token[6:-1]})}\n\n"
                continue
            full_parts.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        result = await future
        reply = "".join(full_parts) or result.get("reply", "")
        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        user_id = await asyncio.to_thread(
            save_entry, "companion", "user", body.message, "text", session_id
        )
        await asyncio.to_thread(
            save_entry, "companion", "assistant", reply, "text", session_id
        )
        asyncio.create_task(_tag_entry(user_id, body.message))
        asyncio.create_task(_sync_corpus())

        yield f"data: {json.dumps({'done': True, 'session_id': session_id, 'reply': reply})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/companion/voice ──────────────────────────────────────────────────────

@app.post("/api/companion/voice")
async def companion_voice(
    file: UploadFile = File(...),
    session_id: str | None = None,
) -> StreamingResponse:
    """Voice input for the companion. Passes PCM natively to Gemma 4 — no ASR round-trip."""
    audio = await file.read()
    suffix = "." + (file.filename or "audio.webm").rsplit(".", 1)[-1]

    try:
        pcm_data = await asyncio.to_thread(_to_pcm_int16, audio, suffix)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    unique_name = f"{uuid.uuid4().hex}{suffix}"
    (AUDIO_DIR / unique_name).write_bytes(audio)
    audio_id = await asyncio.to_thread(save_audio_file, unique_name, len(audio), None)

    sid = session_id or str(uuid.uuid4())
    history, snapshots = await asyncio.gather(
        asyncio.to_thread(get_session_messages, sid),
        asyncio.to_thread(get_recent_mood, 7),
    )
    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None, companion_agent_sync,
            "", history, snapshots, token_q, pcm_data,
        )
        full_parts: list[str] = []
        while True:
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0)
                continue
            if token is None:
                break
            if token.startswith("\x00TOOL:") and token.endswith("\x00"):
                yield f"data: {json.dumps({'tool_call': token[6:-1]})}\n\n"
                continue
            full_parts.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        result = await future
        reply = "".join(full_parts) or result.get("reply", "")
        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        user_id = await asyncio.to_thread(
            save_entry, "companion", "user", "", "voice", sid, audio_id
        )
        await asyncio.to_thread(save_entry, "companion", "assistant", reply, "text", sid)
        asyncio.create_task(_tag_entry(user_id, ""))
        asyncio.create_task(_sync_corpus())

        yield f"data: {json.dumps({'done': True, 'session_id': sid, 'reply': reply})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/journal ──────────────────────────────────────────────────────────────

@app.post("/api/journal")
async def journal(body: JournalBody) -> dict:
    entry_id = await asyncio.to_thread(save_entry, "journal", "user", body.text, body.source, None)
    asyncio.create_task(_tag_entry(entry_id, body.text))
    asyncio.create_task(_sync_corpus())
    return {"id": entry_id, "saved": True}


# ── /api/reflect/open ─────────────────────────────────────────────────────────

@app.get("/api/reflect/open")
async def reflect_open() -> StreamingResponse:
    def _step(msg: str) -> str:
        return f"data: {json.dumps({'step': msg})}\n\n"

    async def generate():
        yield _step("Reading your recent entries…")
        await asyncio.sleep(0)

        snapshots, last_reflect = await asyncio.gather(
            asyncio.to_thread(get_recent_mood, 14),
            asyncio.to_thread(get_last_reflect_summary),
        )
        if not snapshots:
            payload = {
                "greeting": "I haven't seen many entries yet — keep journaling and I'll have more to reflect on.",
                "topics": [{"label": "Something else", "question": "Something else on my mind", "rag_query": "", "type": "free"}],
            }
            yield f"data: {json.dumps({'result': payload})}\n\n"
            return

        yield _step("Finding what stands out…")
        await asyncio.sleep(0)

        result = await asyncio.to_thread(reflect_open_sync, snapshots)

        yield _step("Putting it together…")
        await asyncio.sleep(0)

        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        yield f"data: {json.dumps({'result': result})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/image ────────────────────────────────────────────────────────────────

@app.post("/api/image")
async def upload_image(
    file: UploadFile = File(...),
    note: str = "",
    mode: str = "journal",
    session_id: str | None = None,
) -> dict:
    mime = file.content_type or "application/octet-stream"
    if mime not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {mime}")

    image_bytes = await file.read()
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    ext = mime.split("/")[-1].replace("jpeg", "jpg")
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    dest = IMAGE_DIR / unique_name
    dest.write_bytes(image_bytes)

    image_id = await asyncio.to_thread(save_image_file, unique_name, mime, len(image_bytes))
    entry_id = await asyncio.to_thread(
        save_entry, mode, "user", note.strip(), "image", session_id, None, image_id
    )
    asyncio.create_task(_tag_entry(entry_id, note)) if note.strip() else None
    asyncio.create_task(_sync_corpus())

    return {"entry_id": entry_id, "image_id": image_id, "saved": True}


@app.get("/api/image/{image_id}/file")
async def get_image_file(image_id: int) -> StreamingResponse:
    """Serve the raw image bytes for display in the UI."""
    from .db import _conn as _db_conn
    with _db_conn() as c:
        row = c.execute(
            "SELECT filename, mime_type FROM image_files WHERE id=?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    path = IMAGE_DIR / row["filename"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file missing on disk")

    def _iter():
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(_iter(), media_type=row["mime_type"])


# ── /api/voice (save only) ────────────────────────────────────────────────────

@app.post("/api/voice")
async def voice(
    file: UploadFile = File(...),
    mode: str = "journal",
    session_id: str | None = None,
) -> dict:
    """Save a voice message as raw audio. Background loop will run ASR + tone summary."""
    audio = await file.read()
    orig_name = file.filename or "audio.webm"
    suffix = "." + orig_name.rsplit(".", 1)[-1]
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    (AUDIO_DIR / unique_name).write_bytes(audio)

    audio_id = await asyncio.to_thread(save_audio_file, unique_name, len(audio), None)
    entry_id = await asyncio.to_thread(
        save_entry, mode, "user", "", "voice", session_id, audio_id
    )
    return {"entry_id": entry_id, "audio_id": audio_id, "saved": True}


# ── /api/history ──────────────────────────────────────────────────────────────

@app.get("/api/history")
async def history(view: str = "timeline", day: str | None = None) -> dict:
    rows = await asyncio.to_thread(get_history, view, day)
    return {"entries": rows}


@app.get("/api/stats")
async def stats() -> dict:
    return await asyncio.to_thread(get_stats)


import time as _time
_narrative_cache: dict = {"text": "", "expires": 0.0}

@app.get("/api/insights/narrative")
async def insights_narrative() -> dict:
    now = _time.time()
    if _narrative_cache["text"] and now < _narrative_cache["expires"]:
        return {"narrative": _narrative_cache["text"]}
    stats_data = await asyncio.to_thread(get_stats)
    narrative = await asyncio.to_thread(insight_narrative_sync, stats_data)
    if narrative:
        _narrative_cache["text"] = narrative
        _narrative_cache["expires"] = now + 3600
    return {"narrative": narrative}


# ── helpers ───────────────────────────────────────────────────────────────────

async def _tag_entry(entry_id: int, text: str) -> None:
    try:
        result = await asyncio.to_thread(extract_emotion_sync, text)
        if not result.get("error"):
            await asyncio.to_thread(
                save_mood, entry_id,
                result["valence"], result["intensity"],
                result["category"], result["sub_tags"], result.get("raw", ""),
            )
    except Exception:
        pass
