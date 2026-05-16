# Within: Local-First Emotional Memory with Gemma 4 and Cactus

**Subtitle:** Your journal remembers back—multimodal Gemma on your machine, two models routed by intent.  
**Tracks:** Cactus Special Technology (primary) · Impact — Digital Equity & Inclusivity · Main Track eligible

---

## Abstract

You can vent in a group chat or a side account and feel better for a minute. Those spaces are still built for an audience; fragments rarely become a pattern you can name. **Within** is a private emotion journal with a **Gemma 4** companion: write, speak, or photograph how you feel; see mood over time; ask questions grounded in **your** past entries—all on your machine via **Cactus**. One **google/gemma-4-E2B-it** handle powers chat, tools, streaming, multimodal voice and images, on-device **RAG**, and structured mood JSON. **Parakeet** turns saved journal audio into searchable memory. Optional **Cactus Cloud** (opt-in) may answer generic coping questions without sending your journal. No accounts. No telemetry.

---

## The problem

Emotional expression today is often semi-performative. Even “private” dumps imagine a reader; relief waits on replies. Stress gets released in pieces but not understood across weeks—deadline meetings, comparison, burnout never linked into something you can recognize.

That leaves out people who will not trust a cloud journal, anyone on unreliable networks, and people who think in **voice** more easily than in performative text—including introverts and older adults who do not live on social feeds. They still need a low-friction outlet that does not require likes to feel heard.

**Gemma for Good:** Within builds **emotional literacy** without an audience—not a new feed, but a local system that helps you name what keeps repeating. **Digital equity:** after a one-time model download, inference and your words stay on the device; the journal never uploads to a cloud LLM by default.

---

## The product

Within is a phone-layout **web app** (browser + local FastAPI today; same stack in a native shell later). Four tabs: **Journal**, **Companion**, **History**, **Insights**.

**Journal** is capture-only—text, voice, or photo saves immediately with **no AI reply**, so you are not performing for a bot. **Companion** is where Gemma talks back: an opening greeting and topic cards grounded in recent mood, then chat with streaming replies. **History** and **Insights** turn weeks of private data into calendars, mood chips, and a short narrative over your stats.

A typical loop: you log *“Three meetings before lunch… running on empty.”* Days later you open Companion and ask, *“Why have I felt so drained—is it mostly meetings?”* The agent calls **`search_my_entries`** (semantic search over your exports) and **`get_mood_stats`** (SQLite aggregates). The UI can show those tool steps; the streamed answer cites **your** wording—not a wellness template.

**Two ways to use the microphone** (the core Cactus story): **Companion voice** is record → stop → **Send** → 16 kHz PCM straight into Gemma—live multimodal dialogue, no speech-to-text round trip. **Journal voice** auto-saves, then **Parakeet** transcribes in the background; Gemma tags mood and exports text into the corpus so that moment becomes **memory you can search later**. Same device, different intent.

Opening Companion is **not** the same as ongoing chat: recent mood snapshots drive **rule-based topic cards**, then **`cactus_rag_query`** pulls snippets, then **one** short greeting completion. Every later turn runs the full agent (up to three tool rounds, then stream).

---

## Gemma 4 + Cactus: one engine, routed work

All inference goes through **Cactus**—not separate cloud APIs for chat, embeddings, vision, and ASR.

| What you do | Cactus | Model |
|-------------|--------|--------|
| Companion text / live voice / images | `cactus_complete` (stream) | **Gemma 4 E2B-it** |
| Search your journal (open + tools) | `cactus_rag_query` | Same Gemma handle |
| Saved journal voice → text | `cactus_transcribe` → export | **Parakeet**, then Gemma |
| Mood tags, captions, insights text | `cactus_complete` | Gemma 4 |

**Gemma** loads with `cactus_init(weights, corpus_dir, cache_index=True)` over `corpus/*.txt` files exported from SQLite. **Parakeet** loads with `cactus_init(weights, None, False)`. When new entries are transcribed or captioned, exports update; the server can **re-init** the Gemma handle under a lock so RAG sees fresh text without restarting the app.

We **do not fine-tune**. We use **agentic retrieval** and prompting—the app path the challenge describes:

- **Function calling** — Native tools JSON on `cactus_complete`; non-streaming tool rounds (~0.2 temperature), then a streamed reply (~0.7).
- **Multimodal on E2B** — **Text** for journal and chat; **PCM audio-in** for companion turns; **images** in chat (base64) plus background **captions** on journal photos so pictures become searchable words later.
- **Built-in RAG** — Personal history lives in flat `corpus/*.txt` files; `cactus_rag_query` runs in-process on the same handle—no separate embedding service. That is how Companion and Insights connect this week’s stress to last week’s entries.
- **Structured mood** — Gemma returns JSON in six categories (`stress`, `anxiety`, `low_mood`, `anger`, `social`, `positive`) with validated sub-tags for History chips and charts.
- **Warmup** — A minimal completion prefills the companion system prompt so the first real turn after load is responsive.

**Why E2B is enough:** Journaling needs grounded recall and short, warm replies—not 30B chain-of-thought. On a laptop, E2B already runs multimodal voice-in, visible tool calls, RAG over weeks of entries, and reliable mood JSON. The edge model is small; the **system design** (RAG + tools + routing) makes it capable for this task.

---

## Privacy, safety, and optional cloud

Sensitive work stays local by design. **Journal**, reflect open, mood extraction, and the insights narrative **never** use cloud LLMs.

For Companion only, with `CLOUD_HANDOFF=true`: **crisis** phrases are rule-detected and **always** stay on-device; **coping-style** questions (e.g. “how do I cope with stress?”) may send **only that question** plus a coarse mood label to **Cactus Cloud**—not session history or RAG snippets. If local confidence is low, Cactus **`auto_handoff`** may escalate, but your journal corpus does not leave the machine by default.

Within is **non-clinical**—a journal friend, not a clinician. Tool steps are visible so grounding is inspectable, not a black box.

---

## What we built through

Shipping one Gemma handle for chat, RAG, vision, and JSON while keeping **SSE streaming** responsive meant running Cactus off the asyncio loop with a process-wide lock. The harder product problem was **two voice semantics** in one UX: live PCM dialogue versus Parakeet-backed durable memory. We also refused “fake” RAG—corpus export waits for transcripts and image captions so search does not invent text the user never had.

**Honest scope:** single-user web MVP, not an app-store binary yet; no multi-tenant hosting or cloud sync. The **intent-based routing** is what we would carry to mobile or wearable.

---

## Conclusion

Within shows **Gemma 4** and **Cactus** together for real use: multimodal capture, agentic search over your emotional history, and deliberate routing to **Parakeet** when voice must become durable, searchable memory. The win is simple and human—when your own past entries teach you that meetings and exhaustion keep returning, and you can name that pattern without uploading your inner life.

---

*Attach in Kaggle: public YouTube (≤3 min), GitHub, demo URL, cover image · Non-clinical · Gemma 4 E2B-it · Cactus · Parakeet*
