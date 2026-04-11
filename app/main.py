"""
Within — FastAPI backend.

Start from app root:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import queue
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .db import init_db, save_entry, save_mood, get_session_messages, get_history, get_days_needing_summary, get_day_chat_messages, save_summary, get_corpus_entries, get_stats
from .gemma_cactus import chat_sync, chat_stream_sync, extract_emotion_sync, summarize_sync, reflect_sync, reflect_stream_sync, warmup_sync, export_corpus_incremental, _corpus_cursor
from .transcribe import transcribe_bytes_sync

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Within")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.on_event("startup")
async def startup() -> None:
    init_db()
    asyncio.create_task(_warmup())
    asyncio.create_task(_sync_corpus())
    asyncio.create_task(_archiver_loop())


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


# ── /api/chat ─────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(body: ChatBody) -> dict:
    session_id = body.session_id or str(uuid.uuid4())
    history = await asyncio.to_thread(get_session_messages, session_id)

    try:
        out = await asyncio.to_thread(chat_sync, body.text, history)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if out.get("error"):
        raise HTTPException(status_code=503, detail=out["error"])

    user_id = await asyncio.to_thread(save_entry, "chat", "user", body.text, body.source, session_id)
    await asyncio.to_thread(save_entry, "chat", "assistant", out["reply"], "text", session_id)
    asyncio.create_task(_tag_entry(user_id, body.text))
    asyncio.create_task(_sync_corpus())

    return {"reply": out["reply"], "session_id": session_id, "meta": out.get("meta")}


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


# ── /api/transcribe ───────────────────────────────────────────────────────────

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    audio = await file.read()
    suffix = "." + (file.filename or "audio.webm").rsplit(".", 1)[-1]
    try:
        text = await asyncio.to_thread(transcribe_bytes_sync, audio, suffix)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"text": text}


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
