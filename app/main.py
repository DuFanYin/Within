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
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .db import (
    init_db, save_entry, save_mood,
    save_audio_file, update_audio_transcript, update_entry_content, get_pending_audio_entries,
    save_image_file, update_image_caption, get_pending_image_entries,
    get_session_messages, get_history, get_days_needing_summary, get_day_chat_messages,
    save_summary, get_corpus_entries, get_stats,
)
from .gemma_cactus import chat_stream_sync, extract_emotion_sync, summarize_sync, reflect_sync, reflect_stream_sync, warmup_sync, export_corpus_incremental, _corpus_cursor, tone_summary_sync, image_caption_sync
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
                "-ar", "16000",   # 16 kHz sample rate (Gemma 4 audio encoder)
                "-ac", "1",       # mono
                "-f", "s16le",    # signed 16-bit little-endian PCM
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


app = FastAPI(title="Within")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.on_event("startup")
async def startup() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    asyncio.create_task(_warmup())
    asyncio.create_task(_sync_corpus())
    asyncio.create_task(_archiver_loop())
    asyncio.create_task(_audio_processor_loop())
    asyncio.create_task(_image_processor_loop())


async def _warmup() -> None:
    try:
        await asyncio.to_thread(warmup_sync)
    except Exception:
        pass  # warmup failure is non-fatal; model loads on first real request


async def _sync_corpus() -> None:
    """Export any new journal entries to corpus/ so RAG index is fresh."""
    try:
        import app.gemma_cactus as gc
        entries = await asyncio.to_thread(get_corpus_entries, gc._corpus_cursor)
        if entries:
            await asyncio.to_thread(export_corpus_incremental, entries)
    except Exception:
        pass


async def _archiver_loop() -> None:
    """
    Every 5 minutes: find past days that have chat messages but no summary,
    generate a summary for each, and save it. Runs concurrently with chat.
    """
    CHECK_INTERVAL = 300  # seconds
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            days = await asyncio.to_thread(get_days_needing_summary)
            for day in days:
                asyncio.create_task(_archive_day(day))
        except Exception:
            pass


async def _audio_processor_loop() -> None:
    """
    Every 2 minutes: find voice entries without a transcript yet,
    run ASR + tone summary in background, write back to audio_files,
    then sync to corpus so RAG sees the new text.
    """
    CHECK_INTERVAL = 120  # seconds
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            pending = await asyncio.to_thread(get_pending_audio_entries)
            for item in pending:
                asyncio.create_task(_process_audio_entry(item))
        except Exception:
            pass


async def _image_processor_loop() -> None:
    """
    Every 2 minutes: find image entries without a caption, run image_caption_sync,
    write back to image_files, then re-sync corpus.
    """
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
    """Run image_caption_sync for one image entry and write back the result."""
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
    """
    Run ASR + tone summary for one voice entry and write back results.
    Also backfills entry content and triggers emotion tagging so voice
    entries get mood_snapshots like text entries do.
    """
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
        # Backfill entry content so history page shows the transcript text
        await asyncio.to_thread(update_entry_content, item["entry_id"], transcript)
        # Emotion-tag the entry now that we have text
        asyncio.create_task(_tag_entry(item["entry_id"], transcript))
        # Re-sync corpus so RAG picks up the new voice text
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

class ChatBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    source: str = "text"  # "text" | "voice"


class JournalBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    source: str = "text"


# ── /api/chat/stream ──────────────────────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(body: ChatBody) -> StreamingResponse:
    """
    SSE endpoint: yields tokens as `data: <json>\n\n` lines.
    Final event: `data: {"done": true, "session_id": "...", "meta": {...}}\n\n`
    Error event: `data: {"error": "..."}\n\n`
    """
    session_id = body.session_id or str(uuid.uuid4())
    history = await asyncio.to_thread(get_session_messages, session_id)

    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate():
        # Run blocking FFI call in thread; tokens land in token_q via callback
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None, chat_stream_sync, body.text, history, token_q
        )

        full_reply_parts: list[str] = []

        # Drain the queue until sentinel (None) arrives
        while True:
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                # Yield control so the event loop can do other work
                await asyncio.sleep(0)
                continue

            if token is None:
                break
            full_reply_parts.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        # Await the thread to get meta + check for errors
        meta_result = await future
        full_reply = "".join(full_reply_parts)

        if meta_result.get("error"):
            yield f"data: {json.dumps({'error': meta_result['error']})}\n\n"
            return

        # Persist to DB and kick off emotion tagging
        user_id = await asyncio.to_thread(
            save_entry, "chat", "user", body.text, body.source, session_id
        )
        await asyncio.to_thread(
            save_entry, "chat", "assistant", full_reply, "text", session_id
        )
        asyncio.create_task(_tag_entry(user_id, body.text))

        done_payload: dict = {"done": True, "session_id": session_id}
        if meta_result.get("meta"):
            done_payload["meta"] = meta_result["meta"]
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind proxy
        },
    )


# ── /api/journal ──────────────────────────────────────────────────────────────

@app.post("/api/journal")
async def journal(body: JournalBody) -> dict:
    entry_id = await asyncio.to_thread(save_entry, "journal", "user", body.text, body.source, None)
    asyncio.create_task(_tag_entry(entry_id, body.text))
    asyncio.create_task(_sync_corpus())
    return {"id": entry_id, "saved": True}


# ── /api/reflect ──────────────────────────────────────────────────────────────

class ReflectBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.post("/api/reflect")
async def reflect(body: ReflectBody) -> dict:
    try:
        out = await asyncio.to_thread(reflect_sync, body.question)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if out.get("error"):
        raise HTTPException(status_code=503, detail=out["error"])
    return {"reply": out["reply"], "meta": out.get("meta")}


@app.post("/api/reflect/stream")
async def reflect_stream(body: ReflectBody) -> StreamingResponse:
    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, reflect_stream_sync, body.question, token_q)

        while True:
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0)
                continue
            if token is None:
                break
            yield f"data: {json.dumps({'token': token})}\n\n"

        result = await future
        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        done_payload: dict = {"done": True}
        if result.get("meta"):
            done_payload["meta"] = result["meta"]
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /api/voice ────────────────────────────────────────────────────────────────

@app.post("/api/voice/stream")
async def voice_stream(
    file: UploadFile = File(...),
    session_id: str | None = None,
) -> StreamingResponse:
    """
    Multimodal voice chat (Gemma 4 native audio).
    Converts uploaded audio → PCM int16 → passes directly to cactus_complete.
    Streams the reply as SSE, same format as /api/chat/stream.
    Also saves the raw audio file and journal entry for history/RAG.
    """
    audio = await file.read()
    orig_name = file.filename or "audio.webm"
    suffix = "." + orig_name.rsplit(".", 1)[-1]

    # Convert to PCM int16 for Gemma 4 audio encoder
    try:
        pcm_data = await asyncio.to_thread(_to_pcm_int16, audio, suffix)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Save raw audio for history / background tone summary
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    dest = AUDIO_DIR / unique_name
    dest.write_bytes(audio)
    audio_id = await asyncio.to_thread(save_audio_file, unique_name, len(audio), None)

    sid = session_id or str(uuid.uuid4())
    history = await asyncio.to_thread(get_session_messages, sid)
    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None, chat_stream_sync, "", history, token_q, pcm_data
        )

        full_reply_parts: list[str] = []
        while True:
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0)
                continue
            if token is None:
                break
            full_reply_parts.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        meta_result = await future
        full_reply = "".join(full_reply_parts)

        if meta_result.get("error"):
            yield f"data: {json.dumps({'error': meta_result['error']})}\n\n"
            return

        # Persist voice entry (content empty; background loop fills transcript later)
        user_id = await asyncio.to_thread(
            save_entry, "chat", "user", "", "voice", sid, audio_id
        )
        await asyncio.to_thread(
            save_entry, "chat", "assistant", full_reply, "text", sid
        )
        asyncio.create_task(_sync_corpus())

        done_payload: dict = {"done": True, "session_id": sid}
        if meta_result.get("meta"):
            done_payload["meta"] = meta_result["meta"]
        yield f"data: {json.dumps(done_payload)}\n\n"

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
    """
    2.3: Save an image as an emotional anchor (journal or chat).
    - Validates MIME type and size.
    - Saves file to data/images/.
    - Creates journal_entry with source='image'; content = optional note text.
    - Background _image_processor_loop will generate a caption for RAG.
    """
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

    image_id = await asyncio.to_thread(
        save_image_file, unique_name, mime, len(image_bytes)
    )
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


# ── /api/voice ────────────────────────────────────────────────────────────────

@app.post("/api/voice")
async def voice(
    file: UploadFile = File(...),
    mode: str = "journal",
    session_id: str | None = None,
) -> dict:
    """
    Save a voice message as raw audio for journal entries.
    Background _audio_processor_loop will run ASR + tone summary and write to corpus.
    """
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
