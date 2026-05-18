"""
Within — FastAPI backend.

Start from app root:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import os
from functools import partial
import queue
import time
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from .db import (
    init_db, save_entry, save_mood,
    save_audio_file, update_audio_transcript, update_entry_content, get_pending_audio_entries,
    get_recent_mood,
    save_image_file, get_image_file_row, update_image_caption, get_pending_image_entries,
    get_session_messages, get_history, get_days_needing_summary, get_day_chat_messages,
    save_summary, get_corpus_entries, get_stats,
)
from .corpus import export_corpus_incremental
from . import agent as _agent
from .emotion import extract_emotion_sync, summarize_sync, tone_summary_sync, image_caption_sync, insight_narrative_sync
from .reflect import reflect_open_sync
from .engine import refresh_corpus_index_sync, warmup_sync
from .transcribe import transcribe_bytes_sync

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "data" / "audio"
IMAGE_DIR = ROOT / "data" / "images"

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


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
    await asyncio.to_thread(warmup_sync)


async def _sync_corpus() -> None:
    import app.corpus as _corpus
    entries = await asyncio.to_thread(get_corpus_entries, _corpus._corpus_cursor)
    if entries:
        await asyncio.to_thread(export_corpus_incremental, entries)
        await asyncio.to_thread(refresh_corpus_index_sync)


async def _archiver_loop() -> None:
    while True:
        await asyncio.sleep(300)
        for day in await asyncio.to_thread(get_days_needing_summary):
            asyncio.create_task(_archive_day(day))


async def _audio_processor_loop() -> None:
    while True:
        await asyncio.sleep(120)
        for item in await asyncio.to_thread(get_pending_audio_entries):
            asyncio.create_task(_process_audio_entry(item))


async def _image_processor_loop() -> None:
    while True:
        await asyncio.sleep(120)
        for item in await asyncio.to_thread(get_pending_image_entries):
            asyncio.create_task(_process_image_entry(item))


async def _process_image_entry(item: dict) -> None:
    image_path = IMAGE_DIR / item["filename"]
    caption = await asyncio.to_thread(
        image_caption_sync, str(image_path), item.get("mime_type", "image/jpeg")
    )
    if not caption:
        return
    await asyncio.to_thread(update_image_caption, item["image_id"], caption)
    asyncio.create_task(_sync_corpus())


async def _process_audio_entry(item: dict) -> None:
    audio_path = AUDIO_DIR / item["filename"]
    suffix = "." + item["filename"].rsplit(".", 1)[-1]
    transcript = await asyncio.to_thread(
        transcribe_bytes_sync, audio_path.read_bytes(), suffix
    )
    if not transcript:
        return
    tone = await asyncio.to_thread(tone_summary_sync, transcript)
    await asyncio.to_thread(update_audio_transcript, item["audio_id"], transcript, tone)
    await asyncio.to_thread(update_entry_content, item["entry_id"], transcript)
    asyncio.create_task(_tag_entry(item["entry_id"], transcript))
    asyncio.create_task(_sync_corpus())


async def _archive_day(day: str) -> None:
    messages = await asyncio.to_thread(get_day_chat_messages, day)
    if not messages:
        return
    summary = await asyncio.to_thread(summarize_sync, day, messages)
    if summary:
        await asyncio.to_thread(save_summary, day, summary)


# ── pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.post("/api/warmup")
async def warmup_endpoint() -> dict:
    """Called by the frontend banner; blocks until model is ready."""
    await asyncio.to_thread(warmup_sync)
    return {"ready": True}


# ── dev: one-shot background jobs (same logic as lifespan loops) ─────────────

@app.post("/api/dev/sync-corpus")
async def dev_sync_corpus() -> dict:
    """Run corpus export + RAG refresh once (normally after saves or on startup)."""
    await _sync_corpus()
    return {"ok": True}


@app.post("/api/dev/process-pending-audio")
async def dev_process_pending_audio() -> dict:
    """Process all voice entries waiting for transcription (audio loop body)."""
    pending = await asyncio.to_thread(get_pending_audio_entries)
    for item in pending:
        await _process_audio_entry(item)
    return {"processed": len(pending)}


@app.post("/api/dev/process-pending-images")
async def dev_process_pending_images() -> dict:
    """Caption all images missing captions (image loop body)."""
    pending = await asyncio.to_thread(get_pending_image_entries)
    for item in pending:
        await _process_image_entry(item)
    return {"processed": len(pending)}


@app.post("/api/dev/archive-summaries")
async def dev_archive_summaries() -> dict:
    """Summarize days that need an archive summary (archiver loop body)."""
    days = await asyncio.to_thread(get_days_needing_summary)
    for day in days:
        await _archive_day(day)
    return {"archived": len(days), "days": days}


# ── request models ────────────────────────────────────────────────────────────

class CompanionBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    topic_label: str | None = None
    topic_question: str | None = None
    topic_type: str | None = None
    open_topic: bool = False


class JournalBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    source: str = "text"


async def _companion_sse(
    session_id: str,
    message: str,
    history: list[dict],
    snapshots: list[dict],
    *,
    pcm_data: bytes | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    user_content: str,
    user_source: str,
    audio_id: int | None = None,
    image_id: int | None = None,
    topic_label: str | None = None,
    topic_question: str | None = None,
    topic_type: str | None = None,
    open_topic: bool = False,
) -> StreamingResponse:
    token_q: queue.Queue[str | None] = queue.Queue()

    async def generate() -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None,
            partial(
                _agent.companion_agent_sync,
                message,
                history,
                snapshots,
                token_q,
                pcm_data,
                image_bytes,
                image_mime,
                topic_label=topic_label,
                topic_question=topic_question,
                topic_type=topic_type,
                open_topic=open_topic,
            ),
        )
        full_parts: list[str] = []
        deadline = time.monotonic() + 180
        while True:
            if time.monotonic() > deadline:
                yield f"data: {json.dumps({'error': 'Companion response timed out'})}\n\n"
                return
            try:
                token = token_q.get(timeout=0.05)
            except queue.Empty:
                if future.done():
                    break
                await asyncio.sleep(0)
                continue
            if token is None:
                break
            if token.startswith("\x00TOOL:") and token.endswith("\x00"):
                yield f"data: {json.dumps({'tool_call': token[6:-1]})}\n\n"
                continue
            full_parts.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=30)
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'error': 'Companion agent did not finish'})}\n\n"
            return
        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        reply = result.get("reply") or "".join(full_parts)

        user_id = await asyncio.to_thread(
            save_entry,
            "companion",
            "user",
            user_content,
            user_source,
            session_id,
            audio_id,
            image_id,
        )
        await asyncio.to_thread(
            save_entry, "companion", "assistant", reply, "text", session_id
        )
        if user_source == "text" and user_content.strip():
            asyncio.create_task(_tag_entry(user_id, user_content))
        asyncio.create_task(_sync_corpus())

        done_payload: dict = {"done": True, "session_id": session_id, "reply": reply}
        if result.get("cloud_handoff"):
            done_payload["cloud_handoff"] = True
        if result.get("rule_handoff"):
            done_payload["rule_handoff"] = True
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── /api/companion/chat ───────────────────────────────────────────────────────

@app.post("/api/companion/chat")
async def companion_chat(request: Request) -> StreamingResponse:
    """SSE companion chat. JSON body, or multipart with optional image file."""
    content_type = request.headers.get("content-type", "")
    image_bytes: bytes | None = None
    image_mime: str | None = None
    image_id: int | None = None

    topic_label: str | None = None
    topic_question: str | None = None
    topic_type: str | None = None
    open_topic = False

    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        if not message:
            message = "What do you notice in this photo?"
        session_id = str(form.get("session_id") or "") or str(uuid.uuid4())
        stored_user = message
        upload = form.get("file")
        if upload:
            image_bytes = await upload.read()
            image_mime = upload.content_type or "image/jpeg"
            if image_mime not in _ALLOWED_IMAGE_TYPES:
                raise HTTPException(status_code=415, detail=f"Unsupported image type: {image_mime}")
            if len(image_bytes) > _MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
            ext = image_mime.split("/")[-1].replace("jpeg", "jpg")
            unique_name = f"{uuid.uuid4().hex}.{ext}"
            (IMAGE_DIR / unique_name).write_bytes(image_bytes)
            image_id = await asyncio.to_thread(
                save_image_file, unique_name, image_mime, len(image_bytes)
            )
            entry_id = await asyncio.to_thread(
                save_entry,
                "companion",
                "user",
                message.strip(),
                "image",
                session_id,
                None,
                image_id,
            )
            if message.strip():
                asyncio.create_task(_tag_entry(entry_id, message))
    else:
        try:
            body = CompanionBody.model_validate(await request.json())
        except ValidationError:
            raise HTTPException(status_code=422, detail="Invalid request body")
        message = body.message
        session_id = body.session_id or str(uuid.uuid4())
        topic_label = body.topic_label
        topic_question = body.topic_question
        topic_type = body.topic_type
        open_topic = body.open_topic
        stored_user = (
            f"Opened topic: {topic_label}"
            if open_topic and topic_label
            else message
        )

    history, snapshots = await asyncio.gather(
        asyncio.to_thread(get_session_messages, session_id),
        asyncio.to_thread(get_recent_mood, 7),
    )
    return await _companion_sse(
        session_id,
        message,
        history,
        snapshots,
        image_bytes=image_bytes,
        image_mime=image_mime,
        user_content=stored_user,
        user_source="image" if image_id else "text",
        image_id=image_id,
        topic_label=topic_label,
        topic_question=topic_question,
        topic_type=topic_type,
        open_topic=open_topic,
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
    return await _companion_sse(
        sid,
        "",
        history,
        snapshots,
        pcm_data=pcm_data,
        user_content="",
        user_source="voice",
        audio_id=audio_id,
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
    async def generate():
        yield f"data: {json.dumps({'step': 'Reading your recent entries…'})}\n\n"
        await asyncio.sleep(0)

        snapshots = await asyncio.to_thread(get_recent_mood, 14)
        if not snapshots:
            payload = {
                "greeting": "I haven't seen many entries yet — keep journaling and I'll have more to reflect on.",
                "topics": [{"label": "Something else", "question": "Something else on my mind", "rag_query": "", "type": "just_chat"}],
            }
            yield f"data: {json.dumps({'result': payload})}\n\n"
            return

        yield f"data: {json.dumps({'step': 'Finding what stands out…'})}\n\n"
        await asyncio.sleep(0)

        result = await asyncio.to_thread(reflect_open_sync, snapshots)

        yield f"data: {json.dumps({'step': 'Putting it together…'})}\n\n"
        await asyncio.sleep(0)

        if result.get("error"):
            yield f"data: {json.dumps({'error': result['error']})}\n\n"
            return

        yield f"data: {json.dumps({'result': result})}\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers=_SSE_HEADERS
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
    if note.strip():
        asyncio.create_task(_tag_entry(entry_id, note))
    asyncio.create_task(_sync_corpus())

    return {"entry_id": entry_id, "image_id": image_id, "saved": True}


@app.get("/api/image/{image_id}/file")
async def get_image_file(image_id: int) -> FileResponse:
    """Serve the raw image bytes for display in the UI."""
    row = await asyncio.to_thread(get_image_file_row, image_id)
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(IMAGE_DIR / row["filename"], media_type=row["mime_type"])


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


_narrative_cache: dict = {"text": "", "expires": 0.0}

@app.get("/api/insights/narrative")
async def insights_narrative() -> dict:
    now = time.time()
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
    result = await asyncio.to_thread(extract_emotion_sync, text)
    if not result.get("error"):
        await asyncio.to_thread(
            save_mood, entry_id,
            result["valence"], result["intensity"],
            result["category"], result["sub_tags"], result.get("raw", ""),
        )
