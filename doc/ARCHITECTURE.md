# Within — architecture

This document explains how Within is put together: what runs where, how data moves, and which design choices matter when you change the code. Setup and commands live in the root [README](../README.md).

---

## What Within is

Within is a local-first emotion journal with an on-device AI companion. You capture thoughts as text, voice, or photos; the app extracts structured mood signals, shows history and trends, and offers a conversational companion that can search your past entries and mood patterns. All inference stays on your machine through the [Cactus](https://github.com/cactus-compute/cactus) engine (`third_party/cactus`). There is no login, no cloud API, and no telemetry.

The implementation is a **modular monolith**: one FastAPI process, one SQLite database, one browser client (vanilla JS, no bundler). Complexity lives in how that process schedules work around blocking FFI calls and background enrichment—not in distributed services.

---

## How the system is shaped

The browser loads a single Jinja2 shell (`templates/index.html`) and swaps “pages” with client-side navigation (`static/js/nav.js`). Four bottom-nav areas—**Companion**, **Journal**, **History**, **Insights**—map to different API usage patterns, not different servers.

The server entry point is `app/main.py`. It defines HTTP routes, wraps Cactus work so the asyncio event loop never blocks, and starts long-lived background loops at startup. Feature logic sits in small Python modules (`agent`, `reflect`, `emotion`, `transcribe`, `corpus`, `db`) that call into `app/engine.py` for chat/RAG and `app/transcribe.py` for speech-to-text.

Persistence splits three ways:

- **SQLite** at `data/journal.db` — entries, mood snapshots, metadata for audio/image rows.
- **Files** under `data/audio/` and `data/images/` — raw uploads.
- **Corpus text files** under `corpus/` — flat exports used to build the RAG index at model init.

**Naming trap:** the UI says “Companion” but the template is `reflect.html` and the open flow uses `GET /api/reflect/open`, while ongoing chat uses `/api/companion/*`. In the database, `journal_entries.mode` includes current values `journal` and `companion` plus legacy `chat` and `reflect`. When reading logs or SQL, do not assume the UI label matches the column value.

---

## Runtime model

Understanding Within means understanding how a mostly-async server runs mostly-sync AI code.

**On startup** (`lifespan` in `app/main.py`), the process opens the database, kicks off a one-shot model warmup, syncs any new rows to the corpus directory, and starts three periodic loops (archiver every five minutes; audio and image processors every two minutes). Failures in background work are caught and ignored so a bad file or model glitch does not take down the server.

**On each request**, route handlers stay async. Anything that touches SQLite, the filesystem, or Cactus runs in `asyncio.to_thread` or a thread-pool executor. Companion chat is special: the agent runs in an executor and streams tokens through a `queue.Queue` while the handler yields Server-Sent Events. That pattern keeps Gemma inference off the event loop without losing incremental output.

**After writes**, the server often schedules fire-and-forget tasks: mood extraction (`_tag_entry`) and corpus export (`_sync_corpus`). The client gets a fast response; enrichment catches up shortly after.

**Concurrency on the models:** one shared Gemma handle for chat, completion side-tasks, and RAG, guarded by a lock in `app/engine.py`. A separate lazy Parakeet handle for journal transcription, with its own lock in `app/transcribe.py`. Only one Gemma call runs at a time; ASR can run when the chat lock is free.

---

## Surfaces and their paths

### Companion

The companion is the richest path. Opening the screen calls `GET /api/reflect/open`, which streams progress steps over SSE and ends with a greeting plus suggested topics. Topic selection is mostly client-side: structured topics send a prefixed message into the same chat pipeline as free text.

Each chat turn is `POST /api/companion/chat` (JSON text, or **multipart** with optional image + message), or `POST /api/companion/voice` (audio). All three stream SSE events: `token` for assistant text, `tool_call` when the agent searches entries or mood stats, `done` with `session_id` and full `reply`, or `error`. The client should persist `session_id` across turns; the server loads prior messages for that session from SQLite.

With an image, the server saves the file, embeds it in the user turn as base64 multimodal content, and runs the same agent loop (tools may run before the streamed reply).

When a turn finishes, the server saves user and assistant rows (`mode=companion`), then asynchronously tags mood on the user message and re-exports corpus files.

### Journal

Journal capture is write-optimized. `POST /api/journal` stores text immediately and triggers mood tagging. `POST /api/voice` stores WebM audio and creates an entry with empty content until a background job transcribes it. `POST /api/image` stores the file and optional note; a caption is generated later. In all cases the HTTP response returns before ASR, captioning, or mood extraction complete.

### History

`GET /api/history` serves the timeline and calendar views with mood fields joined from `mood_snapshots`. No streaming.

### Insights

`GET /api/stats` supplies aggregates for charts. `GET /api/insights/narrative` runs a short LLM summary over those stats; the result is cached in memory for one hour.

### Warmup

`POST /api/warmup` blocks until Gemma has done a minimal completion with the companion system prompt (`warmup_sync`). The frontend calls this on first load so the first real chat feels responsive. Lifespan also triggers warmup in the background at boot.

---

## Companion agent

All companion turns funnel through `companion_agent_sync` in `app/agent.py`. The design is deliberately two-phase.

**Phase A — tool rounds (up to three, non-streaming, temperature 0.2):** The model may call `search_my_entries`, which runs semantic search over the corpus via `engine.rag_query`, or `get_mood_stats`, which reads aggregated snapshots from SQLite. Each tool invocation surfaces to the client as a `tool_call` SSE event. Tool results are appended to the message list as `role: tool` turns.

**Phase B — reply (streaming, temperature 0.7):** Tools are disabled. Tokens stream through a callback into the queue. The system prompt is a fixed companion persona (`_COMPANION_SYSTEM`) plus an optional block summarizing mood over the last seven days.

For **voice input on the companion path**, audio is converted with ffmpeg to PCM int16 mono at 16 kHz and passed directly into Gemma as `pcm_data`. There is no Parakeet step—this is native multimodal input, not transcribe-then-chat.

For **text input**, `pcm_data` is omitted. History is rebuilt from `get_session_messages(session_id)` on every turn.

The companion is instructed to stay warm and non-clinical: short replies, at most one question, no unsolicited advice, tools only when they help grounding.

---

## Journal capture and enrichment

Journal voice follows a different audio pipeline than companion voice. Upload accepts the recording immediately; transcription is deferred.

Every two minutes, `_audio_processor_loop` loads pending audio rows, runs `transcribe_bytes_sync` (Parakeet via Cactus), generates a one-line tone summary, writes transcript and tone back to SQLite, updates the journal entry’s `content`, then schedules mood tagging and corpus export. Until that finishes, the entry exists but search and mood may not see the words yet.

Images follow the same “save now, enrich later” pattern: `_image_processor_loop` calls `image_caption_sync`, updates `image_files.caption`, then syncs corpus.

Voice corpus files are only written once a transcript exists (and optionally a `[tone]` block). Image corpus files need a caption. Exports can therefore lag several loop iterations behind the initial save.

---

## Reflect open (not the same as companion chat)

`reflect_open_sync` in `app/reflect.py` does two different kinds of work.

First, **`_decide_insights`** is pure Python over recent mood snapshots: rules emit up to five topic objects (types like `pattern`, `trend`, `tag`, `silence`, `positive`), each with a label and a suggested `rag_query`. No model is used for this step.

Second, a **single greeting completion** may pull short RAG snippets and optional text from the last reflect session, then produce one short sentence. If there is no mood data at all, the code returns a static greeting and a single free-form topic.

After open, there is no separate “reflect chat” API. Every follow-up message uses the companion endpoints described above.

---

## Memory, search, and corpus

Within’s “memory” for the companion is RAG over exported journal text, not raw SQL full-text search on every turn.

When entries gain usable text, `export_corpus_incremental` in `app/corpus.py` writes `corpus/00000042.txt` with date, mode, source, and body. Voice exports can include a `[tone]` section; images use the caption.

At **`cactus_init`** (first chat model load), Cactus indexes whatever `.txt` files already sit in `corpus/`. Search at runtime goes through `rag_query` on that in-process index.

**Index refresh:** after `export_corpus_incremental`, `_sync_corpus` calls `refresh_corpus_index_sync()` in `app/engine.py`. If any `corpus/*.txt` is newer than `index.bin`, the server reloads the Gemma handle with the corpus directory so search picks up new exports—no full process restart. Refresh is skipped if another thread holds the model lock (e.g. companion inference in progress); the next sync retries. Very new entries can still lag until export + a successful refresh.

---

## What gets stored

**`journal_entries`** holds the conversation and journal timeline. Important columns: `mode`, `role` (`user`, `assistant`, or `summary`), `source` (`text`, `voice`, `image`), `content`, `session_id`, and optional `audio_id` / `image_id`.

**`mood_snapshots`** link to an entry after `extract_emotion_sync` succeeds: valence, intensity, one of six categories, and one to three sub-tags validated against that category. Failed extraction is retried once; otherwise no row is written. The taxonomy and prompts live in `app/emotion.py`.

**`audio_files`** and **`image_files`** store filenames and enriched fields (`transcript`, `tone_summary`, `caption`).

Once per day (when the archiver runs), user messages from conversation modes `chat`, `companion`, and `reflect` can be rolled into a `role=summary` entry via `summarize_sync`.

---

## Inference boundary

Within does not embed model weights in its own repo. It expects a built Cactus checkout at `third_party/cactus`, with `libcactus` under `cactus/build/` unless `CACTUS_LIB_PATH` is set.

Two models, two handles:

- **Chat / RAG:** `google/gemma-4-E2B-it` by default (`CACTUS_MODEL_ID`, `CACTUS_WEIGHTS_DIR`, and generation knobs like `CACTUS_MAX_TOKENS`).
- **ASR:** `nvidia/parakeet-tdt-0.6b-v3` by default (`CACTUS_ASR_MODEL_ID`), initialized without a corpus directory.

Other LLM tasks—mood extraction, daily summaries, tone lines, image captions, insights narrative—reuse the chat handle through `engine._run_complete`, not the agent loop.

`shutdown_model` exists but is not called on process exit today; Within also does not use `cactus_stop` or `cactus_reset`.

---

## Design constraints and non-goals

**Local-first and private.** Data and models stay on disk and in process memory on the host. Trust is physical access to the machine, not application-level auth.

**Single user.** No accounts, sessions are companion conversation IDs, not security boundaries.

**Non-clinical.** Prompts position the companion as a journal friend, not a clinician. Mood tags exist to power UI and light analytics, not diagnosis.

**Explicit non-goals today:** multi-user hosting, cloud sync, incremental `cactus_index_add` without reload, and graceful Cactus teardown on shutdown.

---

## Code map

When you need to change behavior, start here:

- **`app/main.py`** — routes, SSE wiring, lifespan loops, ffmpeg PCM helper for companion voice.
- **`app/agent.py`** — companion persona, tools, two-phase agent loop.
- **`app/engine.py`** — Cactus bootstrap, chat model singleton, warmup, RAG, shared completions.
- **`app/transcribe.py`** — journal ASR only.
- **`app/reflect.py`** — reflect open: rules + greeting.
- **`app/emotion.py`** — mood JSON, summaries, captions, insights narrative.
- **`app/corpus.py`** — export format and RAG indexing caveat.
- **`app/db.py`** — schema, queries, archiver mode list.
- **`static/js/reflect.js`** — companion UI, SSE client, session cache.
- **`static/js/journal.js`**, **`recording.js`** — journal capture.
- **`test/test_*.py`**, **`test/e2e/`** — fast HTTP/DB/unit tests; optional e2e with real model (one inference per test).

---

## HTTP reference (compact)

**JSON:** `GET /`, `POST /api/warmup`, `POST /api/journal`, `POST /api/voice`, `POST /api/image`, `GET /api/history`, `GET /api/stats`, `GET /api/insights/narrative`, `GET /api/image/{id}/file`.

**SSE:** `POST /api/companion/chat` (JSON or multipart + image), `POST /api/companion/voice`, `GET /api/reflect/open`.

**Dev-only (tests):** `POST /api/dev/sync-corpus`, `process-pending-audio`, `process-pending-images`, `archive-summaries` — run background pipeline steps once without waiting on lifespan timers.

SSE lines are `data: <json>\n\n`. Companion streams use `token`, `tool_call`, `done`, `error`. Reflect open adds `step` and `result`.
