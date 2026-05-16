# Kaggle Writeup — Within

**Title:** Within: Local-First Emotional Memory and Reflection with Gemma 4  
**Subtitle:** A mobile-layout web app for emotional literacy on your machine—not posts for an audience.

**Track:** Cactus Special Technology Track (primary). Also eligible for Main Track and Impact — Digital Equity & Inclusivity.

---

## Abstract

Social expression is built for an audience: relief fades when replies do not come, and the same stress gets vented in fragments that never become a pattern you can name. **Within** is a **mobile-first web app** (browser + local FastAPI, **not** an App Store or Play build): journal in private, talk to a grounded companion, see moods over time. **Cactus** on the host routes **Gemma 4** and **Parakeet** by intent—live dialogue and retrieval on one handle, durable voice memory on another—with **no cloud LLM at inference time**.

---

## At a glance

- **What ships:** Phone-layout UI in the browser; FastAPI, SQLite, `corpus/`, and Cactus on the **same machine** as the data (typical run: `uvicorn` → `http://127.0.0.1:8765`; optional phone on LAN).
- **Not shipping (this submission):** Native mobile binary, wearable client, or installable PWA—routing and on-device inference are the prize story; packaging is a later wrap.
- **Cactus routing:** Gemma for companion chat (incl. PCM voice-in), RAG, vision, JSON mood, summaries; Parakeet for **saved** journal audio → transcript → memory.
- **Gemma 4 in use:** Function calling, streaming SSE, multimodal audio-in, schema-constrained extraction—no fine-tuning.
- **Audit in repo:** `app/engine.py`, `app/agent.py`, `app/transcribe.py`, `app/emotion.py`, `app/corpus.py`.

---

## 1. Problem

At 1 a.m., someone posts in a feelings channel or a side account. They check for replies. None come. They vented about the same deadline three times this week, yet nothing connects.

People do not lack emotion; they lack a place where expression becomes **understanding**—**emotional literacy** without performing for a feed or outsourcing regulation to likes and silence.

Introverts, people on unreliable networks, and anyone who needs real privacy are poorly served by cloud journals and social dumps. **Digital Equity & Inclusivity** here means private expression without another public account, voice-friendly capture, and tools that work after weights are downloaded—not only on always-on cloud APIs. What is missing is continuity without performance: a system that remembers *your* words back to you, on a machine you control.

---

## 2. Within: product and journey

**Within** is a **web app MVP**: four feature surfaces in a phone-sized shell (Journal, Companion, History, Insights), served by local FastAPI—**not** a packaged native or wearable app. Inference and data stay on the host running the server; the browser is the client. This is not diagnosis, crisis automation, or therapy.

After a week of deadline stress logged as voice notes and short entries, Companion searches those fragments, pulls mood aggregates, and asks about meetings—not engagement metrics. The user can **name the pattern for the first time** without posting for anyone else. That is the product goal: private memory that remembers back.

| Step | User | Cactus (on host) |
|------|------|------------------|
| **Capture** | Text, voice, or photo in Journal (save returns immediately) | SQLite → background **Parakeet** ASR, then **Gemma** mood JSON, captions, tone lines |
| **Return** | Companion greeting + topic cards | App mood rules + **`cactus_rag_query`** → **`cactus_complete`** greeting |
| **Talk** | Chat or hold-to-talk (PCM into Gemma; no live ASR) | Tool rounds + streamed **`cactus_complete`** |
| **Patterns** | History + Insights | SQLite charts + **`cactus_complete`** narrative |

---

## 3. Why local-first — and Cactus track fit

Sensitive journaling needs architecture where reasoning never leaves the machine. After one-time weight download (`cactus download` / `ensure_model`), **inference runs fully offline** on that host.

The **Cactus Special Technology Track** asks for a **local-first mobile or wearable** app that **intelligently routes tasks between models**. Within delivers the same on-device **Cactus** runtime and **intent-based routing** in a **mobile-first web MVP** today—the routing design is what we would ship inside a native shell later, without changing which model handles dialogue versus memory.

That matters for dorm or rural Wi‑Fi, users who will not trust a cloud vendor with intimate text, and people who express better by voice—including older adults who do not want another social account. **Cactus** replaces a patchwork of cloud APIs (chat, embeddings, ASR, vision) with one local runtime.

**How you run it:** clone the repo, build Cactus, start `uvicorn`, open the app in a desktop or phone browser. Same-host demo is the inspectable proof; LAN access is optional for judging on a real phone viewport.

---

## 4. How I use Cactus (and Gemma 4 through it)

A user who journals at night should not wait on cloud ASR before they can sleep. A user who talks to Companion should not block on transcription—the reply path is different from the memory path. **Within routes by intent**, not by calling one model for everything.

There is **no cloud LLM client** in the app. All generation and retrieval go through **Cactus** (`libcactus` + Python FFI from `third_party/cactus`, cloned and built per README). FastAPI owns HTTP, SQLite, SSE, and background jobs; Cactus owns models.

### Two handles, one evening

| Intent | Cactus API | Model |
|--------|------------|-------|
| Live companion (text / PCM voice) | `cactus_complete` + stream callback | **Gemma 4 E2B-it** |
| Search personal history (Reflect, tools) | `cactus_rag_query` | Gemma (retrieval over exported corpus; index rebuilt when `corpus/` is newer than `index.bin`) |
| Saved journal voice → searchable memory | `cactus_transcribe` → DB → export | **Parakeet** → Gemma for tags/summaries |
| Vision, mood JSON, daily/insights text | `cactus_complete` | Gemma 4 |

**Gemma** loads with `cactus_init(weights, corpus_dir, cache_index=True)` over `corpus/*.txt`. **Parakeet** loads lazily with `cactus_init(weights, None, False)`. Same microphone, two jobs: **conversation** (ffmpeg → PCM → Gemma multimodal input) versus **memory** (WebM on disk → transcribe → mood + corpus export).

**Example evening:** User saves a journal voice note (`POST /api/voice`)—response is immediate; ~two minutes later a background loop runs **`cactus_transcribe`**, writes the transcript, **`cactus_complete`** extracts mood JSON, and exports `corpus/00000042.txt`. Later they open Companion and ask why they feel drained. **`companion_agent_sync`** runs up to three non-streaming **`cactus_complete`** tool rounds (`search_my_entries` → **`cactus_rag_query`**, `get_mood_stats` → SQLite), then streams the reply. If they hold the mic, audio skips Parakeet and enters Gemma as **PCM**—low-latency dialogue, not the journal pipeline.

**Gemma modes** (one handle, many prompts): bounded companion chat with mood context; Reflect greeting after retrieval (topics from Python rules in `reflect.py`); strict JSON mood tags; image captions; tone summaries; daily archiver and Insights narrative. Grounding comes from **agentic retrieval**, schema-constrained extraction, and task-specific temperatures (0.1 mood JSON, 0.2 tool rounds, 0.7 companion stream)—not fine-tuning.

### Engineering and limits

A process-wide lock serializes Gemma FFI; `asyncio.to_thread` and an executor keep SSE responsive. **Warmup** prefills the companion system prompt. Conversation state lives in **SQLite**, not the engine.

| Limit | Why it matters |
|-------|----------------|
| Web client, not native app | Browser + local server; no store binary in this repo |
| Index reload, not `cactus_index_add` | New exports trigger `refresh_corpus_index_sync()` (re-init with corpus); skipped if the model lock is held |
| Journal ASR is async | Voice entries enrich on a ~2 min loop |
| Companion voice not auto-transcribed to corpus | PCM is for dialogue; durable text uses the journal pipeline |
| `ffmpeg` required | Companion PCM conversion |
| No mid-generation cancel | Not wired in this MVP |

---

## 5. Challenges overcome

- **One Gemma handle, many jobs** — Chat, RAG, vision, JSON, and summaries share one FFI handle; serialization plus thread offload preserve streaming UX in a web client.
- **Two voice pipelines** — PCM dialogue vs Parakeet-backed memory; both through Cactus, chosen by product intent.
- **Structure from messy prose** — Controlled mood vocabulary, validation, single retry; tags scaffold charts, not clinical labels.
- **Grounding without cloud** — Corpus export waits for transcripts/captions; background index refresh plus in-session tools keep search current without a cloud API.
- **Trust** — Non-clinical prompts; tool calls surface in the UI; retrieval is explicit.

---

## 6. Trade-offs and future work

**Mobile-first in the browser** keeps the stack judge-inspectable and avoids store or account gatekeeping while still targeting phone capture flows (voice, bottom nav, single-hand use). Structured tags trade nuance for readable History. RAG refresh reloads the handle when corpus files change (not incremental `cactus_index_add`); latency depends on local hardware.

**Next:** wrap the same Cactus routing in a native shell or PWA; finer-grained index updates; multilingual Gemma/ASR—without sending journals upstream.

---

## 7. Conclusion

**Within** answers the Cactus prize: **local-first, model routing by user intent**—Gemma for dialogue, retrieval, vision, and structure; Parakeet for offline transcription into memory. The **mobile-first web MVP** is the shippable proof in this repo: dual `cactus_init`, agentic tools, streaming multimodal voice, and honest limits—ready to port, not a different architecture.

The human payoff is emotional literacy without an audience—when your own past entries, not a feed, teach you what kept repeating.

---

*Non-clinical · Cactus + Gemma 4 + Parakeet · browser client; inference on host after weights are downloaded*
