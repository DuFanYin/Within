# Within: Local-First Emotional Memory with Gemma 4 and Cactus

**Subtitle:** Private reflection that turns text, voice, and photos into searchable emotional memory.  
**Tracks:** Cactus Special Technology (primary) · Digital Equity & Inclusivity · Main Track eligible

---

## Abstract

People already use side accounts, voice notes, and private dumps to release emotion. What they usually do not get is continuity: the ability to come back later and understand what keeps repeating. **Within** is a local-first emotion journal built with **Gemma 4** and **Cactus** that helps people capture how they feel, revisit their history, and ask grounded questions about their own past entries.

The app runs on the user’s machine by default. One **google/gemma-4-E2B-it** handle powers streaming chat, function calling, multimodal voice and image input, on-device RAG, and structured mood JSON. **Parakeet** turns saved journal audio into searchable memory. Optional **Cactus Cloud** is available only for a narrow set of non-sensitive companion questions when the user enables it. No account. No telemetry. The journal stays private.

---

## The problem

Emotional expression online often looks private, but it still happens under the pressure of an imagined audience. Even when nobody replies, the user is still performing, editing, or waiting for feedback. That makes it hard to turn scattered moments into understanding.

This leaves out people who do not trust cloud products with sensitive thoughts, have unreliable internet, or think more naturally in voice than polished text. It also leaves out anyone who wants a calm, low-friction place to reflect without being watched.

The challenge prompt asked for a Gemma 4 project with real-world utility, grounded outputs, and meaningful impact. Within targets **Digital Equity & Inclusivity** by making emotional reflection accessible in a format that is private, local, and easy to use.

---

## What Within does

Within is a phone-layout web app with four core areas:

- **Journal** for private capture without reply,
- **Companion** for grounded conversation,
- **History** for browsing past entries,
- **Insights** for trends and mood patterns.

The product intentionally separates two kinds of use. **Journal** is capture-first: text, voice, or photo saves immediately, and the app does not talk back. **Companion** is for reflection: it opens with a short greeting and topic suggestions based on recent mood history, then supports streaming conversation grounded in the user’s own entries.

That separation matters. Some moments need to be recorded. Others need help connecting the dots.

---

## How Gemma 4 is used

Within uses Gemma 4 as a routed system, not as a generic chatbot.

| User need | Cactus path | Model |
|---|---|---|
| Companion text, voice, image chat | `cactus_complete` with streaming | Gemma 4 E2B-it |
| Search personal memory | `cactus_rag_query` over exported journal text | Same Gemma handle |
| Journal voice transcription | `cactus_transcribe` | Parakeet, then Gemma |
| Mood tags, captions, insight text | `cactus_complete` | Gemma 4 E2B-it |

Two things matter here.

First, **Gemma 4 is truly multimodal in the product path**: the companion can reason over text, live voice, and images. Second, **answers are grounded**. The app can call `search_my_entries` and `get_mood_stats` so the model responds using the user’s own history instead of generic wellness language. The UI can even surface those tool steps, so the grounding is inspectable rather than implied.

I did not fine-tune the model. The point of the project was to make the system design do the work: retrieval, structured outputs, background enrichment, and a UI that keeps the model honest.

---

## Why Cactus

Cactus is the right fit because this project needs one local-first runtime for chat, retrieval, multimodal input, and ASR. Within does not split those pieces across separate services. That keeps the architecture simpler and keeps sensitive data on-device by default.

The routing story is also part of the product. Here, “routing” means deciding whether a companion question stays local or can be handed off to cloud. Sensitive work stays on-device. Only a narrow set of generic coping questions can use **Cactus Cloud**, and even then the app sends only the current question plus a coarse mood label, not the user’s journal history.

That makes the privacy story practical. The app still works offline or on weak networks, but it also has an escape hatch for non-sensitive questions when the user wants it.

---

## Architecture and implementation

Within is a single FastAPI app with SQLite, background enrichment jobs, and a vanilla JS frontend. The hardest engineering problem was making blocking AI work fit cleanly inside an async web server.

The key implementation choices were:

- one shared Gemma handle for chat, retrieval, captions, mood extraction, and narratives,
- a separate Parakeet path for journal transcription,
- SSE streaming for companion replies so the user sees progress immediately,
- delayed enrichment for voice and image entries so capture stays fast,
- corpus export and refresh so new entries become searchable without a full restart.

This is how the memory story becomes real. The companion does not invent long-term memory; it searches exported journal text, then uses that context to answer the user. That means the app can actually say things like “your stress tends to cluster around meetings” because it is grounded in the user’s own history.

---

## The hardest product problem

The biggest UX challenge was supporting two different voice semantics in one app:

- **Companion voice** is live conversation: audio goes directly into Gemma and the user gets a streamed reply.
- **Journal voice** is durable memory: audio is saved first and transcribed in the background so it can be searched later.

That split matters because not every spoken thought should become a conversation. Some moments should just be preserved.

I also avoided fake retrieval. New transcripts and photo captions only enter the corpus after enrichment, so search reflects real user content rather than assumptions. That makes the system more trustworthy and the grounded replies more honest.

---

## Why this matters

Within is designed to build emotional literacy, not diagnosis. It helps people notice patterns in their own words over time: stress after deadlines, loneliness after long gaps, or a good week worth remembering. That is a small but meaningful form of support, especially for people who are often missed by cloud-first, social, or highly performative tools.

The combination of **local privacy**, **multimodal capture**, **agentic retrieval**, and **structured mood understanding** is what makes Gemma 4 useful here. The model is small enough to run locally, but the system around it turns it into something practical and humane.

---

## Conclusion

Within shows Gemma 4 and Cactus as a real local-first product, not just a demo of model capability. It supports private capture, grounded reflection, searchable emotional memory, and optional handoff for non-sensitive questions when appropriate.

The core idea is simple: people should be able to express how they feel without performing for an audience, and later come back to a system that helps them understand what keeps repeating. Within is my attempt to make that possible on the user’s own device.

---

*Submission assets: public YouTube video, public code repository, live demo, and cover image.*
