"""
Local Gemma 4 (google/gemma-4-E2B-it) via Cactus Python FFI.

The engine checkout is resolved in order: ``CACTUS_PROJECT_ROOT``,
``<app_root>/third_party/cactus``, then walking parents for ``python/src/cactus.py``.

``libcactus`` is loaded from ``<engine>/cactus/build/libcactus.{dylib,so}`` unless
``CACTUS_LIB_PATH`` is already set to a file.

Weights from ``ensure_model`` live under ``<engine>/weights/`` (or ``CACTUS_WEIGHTS_DIR``).
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import queue
import sys
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_model: int | None = None
_weights_used: str | None = None
_corpus_cursor: int = 0  # last exported entry id


def _corpus_dir() -> Path:
    p = _app_root() / "corpus"
    p.mkdir(exist_ok=True)
    return p


def export_corpus_incremental(entries: list[dict]) -> int:
    """
    Write new journal/chat entries to corpus/ as individual text files.
    For voice entries, prefer transcript over empty content; append tone_summary
    as a separate labelled block so RAG can retrieve both what was said and how.
    Returns the new cursor (max id exported), or 0 if nothing new.
    """
    global _corpus_cursor
    if not entries:
        return _corpus_cursor
    corpus = _corpus_dir()
    for e in entries:
        fname = corpus / f"{e['id']:08d}.txt"
        date = e["created_at"][:10]
        mode = e["mode"]
        source = e.get("source", "text")

        if source == "voice":
            transcript = (e.get("transcript") or "").strip()
            tone = (e.get("tone_summary") or "").strip()
            if not transcript:
                # transcript not ready yet; skip — re-exported after background ASR
                continue
            body = f"[{date}] [{mode}] [voice]\n{transcript}\n"
            if tone:
                body += f"\n[tone]\n{tone}\n"
        elif source == "image":
            caption = (e.get("image_caption") or "").strip()
            if not caption:
                # caption not ready yet; skip — re-exported after background captioning
                continue
            body = f"[{date}] [{mode}] [image]\n{caption}\n"
            text_note = (e.get("content") or "").strip()
            if text_note:
                body += f"\n[note]\n{text_note}\n"
        else:
            body = f"[{date}] [{mode}]\n{e['content']}\n"

        fname.write_text(body, encoding="utf-8")

    new_cursor = entries[-1]["id"]
    _corpus_cursor = new_cursor
    return new_cursor

# ── path helpers ──────────────────────────────────────────────────────────────

def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _third_party_engine() -> Path:
    return _app_root() / "third_party" / "cactus"


def _repo_root() -> Path:
    env = os.environ.get("CACTUS_PROJECT_ROOT", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "python" / "src" / "cactus.py").is_file():
            return p
        raise RuntimeError(f"CACTUS_PROJECT_ROOT invalid: {p}")
    bundled = _third_party_engine()
    if (bundled / "python" / "src" / "cactus.py").is_file():
        return bundled
    start = _app_root()
    for candidate in [start, *start.parents]:
        if (candidate / "python" / "src" / "cactus.py").is_file():
            return candidate
    raise RuntimeError(
        "Could not find Cactus engine checkout. Clone/build into third_party/cactus "
        "or set CACTUS_PROJECT_ROOT to a tree containing python/src/cactus.py."
    )


def _ensure_python_path() -> Path:
    root = _repo_root()
    py = root / "python"
    if not py.is_dir():
        raise RuntimeError(f"Cactus python package not found at {py}")
    s = str(py)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)
    os.environ.setdefault("CACTUS_PROJECT_ROOT", str(root))

    _libname = "libcactus.dylib" if platform.system() == "Darwin" else "libcactus.so"
    existing = os.environ.get("CACTUS_LIB_PATH", "").strip()
    if existing:
        lib_path = Path(existing).expanduser().resolve()
        if not lib_path.is_file():
            raise RuntimeError(f"CACTUS_LIB_PATH is not a file: {lib_path}")
        os.environ["CACTUS_LIB_PATH"] = str(lib_path)
        return root

    built = root / "cactus" / "build" / _libname
    if not built.is_file():
        raise RuntimeError(
            f"Cactus shared library not found at {built}. "
            "In the engine checkout run: source ./setup && cactus build --python"
        )
    os.environ["CACTUS_LIB_PATH"] = str(built)
    return root


def _load_cactus():
    _ensure_python_path()
    try:
        cactus_mod = importlib.import_module("src.cactus")
        downloads_mod = importlib.import_module("src.downloads")
    except (RuntimeError, OSError, ImportError, AttributeError) as e:
        raise RuntimeError(f"Failed to load Cactus Python FFI: {e!r}") from e
    return (
        cactus_mod.cactus_init,
        cactus_mod.cactus_complete,
        cactus_mod.cactus_destroy,
        cactus_mod.cactus_get_last_error,
        downloads_mod.ensure_model,
    )


def _resolve_weights(ensure_model) -> Path:
    override = os.environ.get("CACTUS_WEIGHTS_DIR", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if not (p / "config.txt").is_file():
            raise RuntimeError(f"CACTUS_WEIGHTS_DIR missing config.txt: {p}")
        return p
    model_id = os.environ.get("CACTUS_MODEL_ID", "google/gemma-4-E2B-it").strip()
    precision = os.environ.get("CACTUS_WEIGHTS_PRECISION", "INT4").strip()
    return ensure_model(model_id, precision=precision)


def _get_model() -> tuple[Any, Any, Any, Any]:
    global _model, _weights_used
    if _model is not None:
        cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, _ = _load_cactus()
        return cactus_complete, cactus_destroy, cactus_get_last_error, _model
    with _lock:
        if _model is not None:
            cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, _ = _load_cactus()
            return cactus_complete, cactus_destroy, cactus_get_last_error, _model
        cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, ensure_model = _load_cactus()
        weights = _resolve_weights(ensure_model)
        corpus = str(_corpus_dir())
        handle = cactus_init(str(weights), corpus, True)
        if not handle:
            err = cactus_get_last_error() or "unknown"
            raise RuntimeError(f"cactus_init failed: {err}")
        _model = handle
        _weights_used = str(weights)
    return cactus_complete, cactus_destroy, cactus_get_last_error, _model


def _base_options() -> dict[str, Any]:
    return {
        "max_tokens": int(os.environ.get("CACTUS_MAX_TOKENS", "512")),
        "temperature": float(os.environ.get("CACTUS_TEMPERATURE", "0.7")),
        "top_p": float(os.environ.get("CACTUS_TOP_P", "0.9")),
        "top_k": int(os.environ.get("CACTUS_TOP_K", "40")),
        "enable_thinking_if_supported": os.environ.get("CACTUS_ENABLE_THINKING", "false").lower() == "true",
    }


_SYSTEM_PROMPT = (
    "You are a warm, private companion for an emotion journal. "
    "The user shares personal feelings with you. "
    "Listen carefully, respond with empathy and gentle reflection. "
    "Keep responses concise (2-4 sentences). "
    "Never diagnose or treat medical or psychiatric conditions. "
    "If the user seems in crisis, gently suggest professional support."
)


def _run_complete(
    messages: list[dict],
    options: dict,
    pcm_data: bytes | None = None,
) -> dict[str, Any]:
    cactus_complete, _, cactus_get_last_error, model = _get_model()
    with _lock:
        raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, None, pcm_data)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from cactus_complete", "reply": raw[:2000]}
    if not result.get("success"):
        err = result.get("error") or cactus_get_last_error() or "completion failed"
        return {"error": str(err), "reply": ""}
    reply = result.get("response") or ""
    meta = {k: result[k] for k in (
        "time_to_first_token_ms", "total_time_ms",
        "prefill_tps", "decode_tps", "ram_usage_mb", "total_tokens",
    ) if k in result}
    out: dict[str, Any] = {"reply": reply}
    if meta:
        out["meta"] = meta
    return out


# ── public API ────────────────────────────────────────────────────────────────

def chat_stream_sync(
    user_text: str,
    history: list[dict] | None,
    token_queue: "queue.Queue[str | None]",
    pcm_data: bytes | None = None,
) -> dict[str, Any]:
    """
    Like chat_sync but streams tokens into ``token_queue`` as they're produced.
    Pass pcm_data (PCM int16 raw bytes) to send audio directly to Gemma 4.
    Puts ``None`` as a sentinel when generation finishes (or on error).
    Returns the same meta dict as chat_sync (reply is empty string; caller
    reconstructs the full reply from the queue).
    """
    cactus_complete, _, _, model = _get_model()

    # For audio input, content is empty string — the model reads from pcm_data
    user_content = user_text if not pcm_data else (user_text or "")
    messages = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + (history or [])
        + [{"role": "user", "content": user_content}]
    )
    options = _base_options()

    def _on_token(token_str: str, _token_id: int) -> None:
        if token_str:
            token_queue.put(token_str)

    cb = _on_token

    try:
        with _lock:
            raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, cb, pcm_data)
    except Exception as exc:
        token_queue.put(None)
        return {"error": str(exc), "reply": ""}

    token_queue.put(None)  # sentinel

    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"reply": ""}

    if not result.get("success"):
        return {"error": result.get("error") or "stream_failed", "reply": ""}

    meta = {k: result[k] for k in (
        "time_to_first_token_ms", "total_time_ms",
        "prefill_tps", "decode_tps", "ram_usage_mb", "total_tokens",
    ) if k in result}
    return {"reply": "", "meta": meta} if meta else {"reply": ""}


_VALID_CATEGORIES = {"positive", "stress", "anxiety", "low_mood", "anger", "social"}

_CATEGORY_SUB_TAGS = {
    "positive": {"happy", "content", "relaxed", "excited", "accomplished"},
    "stress": {"busy", "exhausted", "overwhelmed", "time_crunched", "drained"},
    "anxiety": {"worried", "tense", "uneasy", "out_of_control", "future_anxiety"},
    "low_mood": {"sad", "empty", "helpless", "lost", "unmotivated"},
    "anger": {"angry", "irritable", "unfair", "offended", "suppressed_anger"},
    "social": {"lonely", "overlooked", "ashamed", "jealous", "comparison_anxiety"},
}

_EXTRACT_SYSTEM = (
    "You are an emotion analysis system. "
    "Given a journal entry, respond with ONLY valid JSON in this exact format:\n"
    '{"valence": <float -1.0 to 1.0>, "intensity": <float 0.0 to 1.0>, '
    '"category": <one of the six categories below>, "sub_tags": [<1-3 tags from that category>]}\n\n'
    "category must be exactly one of: positive, stress, anxiety, low_mood, anger, social\n\n"
    "sub_tags must be chosen ONLY from the list for the chosen category:\n"
    "- positive: happy, content, relaxed, excited, accomplished\n"
    "- stress: busy, exhausted, overwhelmed, time_crunched, drained\n"
    "- anxiety: worried, tense, uneasy, out_of_control, future_anxiety\n"
    "- low_mood: sad, empty, helpless, lost, unmotivated\n"
    "- anger: angry, irritable, unfair, offended, suppressed_anger\n"
    "- social: lonely, overlooked, ashamed, jealous, comparison_anxiety\n\n"
    "No explanation, no markdown, just the JSON object."
)


def extract_emotion_sync(text: str) -> dict[str, Any]:
    """
    Extract structured emotion using the two-level category system.
    Returns {valence, intensity, category, sub_tags, raw} or {error}.
    Retries once on schema failure.
    """
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": text},
    ]
    options = {**_base_options(), "temperature": 0.1, "top_k": 1, "max_tokens": 100}

    for _ in range(2):
        result = _run_complete(messages, options)
        if result.get("error"):
            continue
        raw = result.get("reply", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            parsed = json.loads(raw)
            v = float(parsed.get("valence", 0))
            i = float(parsed.get("intensity", 0.5))
            category = str(parsed.get("category", "")).strip()
            if category not in _VALID_CATEGORIES:
                continue
            valid_subs = _CATEGORY_SUB_TAGS[category]
            sub_tags = [t for t in parsed.get("sub_tags", []) if str(t) in valid_subs][:3]
            return {
                "valence": max(-1.0, min(1.0, v)),
                "intensity": max(0.0, min(1.0, i)),
                "category": category,
                "sub_tags": sub_tags,
                "raw": raw,
            }
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    return {"valence": None, "intensity": None, "category": None, "sub_tags": [], "raw": "", "error": "parse_failed"}


_WARMUP_DONE = False


def warmup_sync() -> None:
    """
    Load the model and prefill the system prompt so the first real user
    request skips cold-start latency. Safe to call multiple times.
    """
    global _WARMUP_DONE
    if _WARMUP_DONE:
        return
    cactus_complete, _, cactus_get_last_error, model = _get_model()
    # prefill: send system + a minimal placeholder user turn
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "Hello"},
    ]
    options = {**_base_options(), "max_tokens": 1}  # generate almost nothing; just prefill KV
    with _lock:
        cactus_complete(model, json.dumps(messages), json.dumps(options), None, None)
    _WARMUP_DONE = True


_IMAGE_CAPTION_SYSTEM = (
    "You are a gentle journaling companion helping a user build emotional memories. "
    "The user has attached a photo to their journal. "
    "Write a short, warm description (2-3 sentences) of what this image likely represents as an emotional anchor — "
    "the mood, setting, or feeling it might evoke. "
    "Do not invent facts. If the image is abstract or unclear, describe the general atmosphere. "
    "No bullet points. No clinical language."
)


def image_caption_sync(image_path: str, mime_type: str = "image/jpeg") -> str:
    """
    Generate a short emotional/contextual caption for an image (plan 2.3).
    Returns a 2-3 sentence description for RAG indexing.
    Returns empty string on failure.

    Note: uses the text model with a description of the image encoded as base64
    if the model supports vision; otherwise falls back to a placeholder.
    """
    import base64
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError:
        return ""

    # Build a vision-style message. Cactus/Gemma 4 supports image_url content parts.
    messages = [
        {"role": "system", "content": _IMAGE_CAPTION_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
                {"type": "text", "text": "Please describe this photo as an emotional memory anchor."},
            ],
        },
    ]
    options = {**_base_options(), "temperature": 0.5, "max_tokens": 120}
    result = _run_complete(messages, options)
    return result.get("reply", "").strip()


_TONE_SYSTEM = (
    "You are an assistant that analyzes the expressive quality of spoken transcripts. "
    "Given a transcript, write ONE short paragraph (2-4 sentences) describing HOW the person spoke — "
    "not what they said, but the tone, pace, and emotional texture: "
    "e.g. hesitations, fatigue, urgency, emotional weight, uncertainty, warmth. "
    "Be observational and gentle. No bullet points. No clinical language."
)


def tone_summary_sync(transcript: str) -> str:
    """
    Generate a tone/expressiveness summary for a voice transcript (plan 2.2).
    Returns a short paragraph describing *how* the person spoke.
    Returns empty string on failure.
    """
    messages = [
        {"role": "system", "content": _TONE_SYSTEM},
        {"role": "user", "content": transcript},
    ]
    options = {**_base_options(), "temperature": 0.5, "max_tokens": 150}
    result = _run_complete(messages, options)
    return result.get("reply", "").strip()


def summarize_sync(day: str, user_messages: list[str]) -> str:
    """
    Generate a concise daily summary from a list of user chat messages.
    Returns the summary string, or an empty string on failure.
    """
    joined = "\n".join(f"- {m}" for m in user_messages)
    system = {
        "role": "system",
        "content": (
            "You are a gentle, reflective journaling companion. "
            "Your role is to write a warm end-of-day summary for the user based on what they shared today. "
            "Write in second person (e.g. 'You…'). "
            "Be empathetic, non-judgmental, and thoughtful (5–8 sentences). "
            "Focus on emotional themes and the overall feeling of the day, not just a list of events. "
            "Synthesize and reflect — do not repeat every detail verbatim. "
            "No bullet points."
        ),
    }
    messages = [
        system,
        {"role": "user", "content": f"Here are the things I shared on {day}:\n{joined}\n\nWrite a summary of my emotional day."},
    ]
    options = {**_base_options(), "temperature": 0.6, "max_tokens": 350}
    result = _run_complete(messages, options)
    return result.get("reply", "").strip()


# ── Insight agent ─────────────────────────────────────────────────────────────

def _decide_insights(snapshots: list[dict]) -> list[dict]:
    """
    Pure-code decision layer. Takes recent mood snapshots and returns up to 5
    insight descriptors. No LLM involved here.

    Each descriptor:
      { type, label, rag_query, evidence, priority }
      - type: "pattern" | "trend" | "tag" | "silence" | "positive"
      - label: short human-readable label shown on the step card
      - rag_query: string to pass to cactus RAG retrieval
      - evidence: dict of supporting stats (shown in C-step UI)
      - priority: int, lower = more important
    """
    from collections import Counter, defaultdict
    from datetime import date, timedelta

    insights: list[dict] = []

    if not snapshots:
        insights.append({
            "type": "silence",
            "label": "No recent entries",
            "rag_query": "how I feel",
            "evidence": {},
            "priority": 5,
        })
        return insights

    # ── aggregate by day ──────────────────────────────────────────────────────
    days_seen: set[str] = {s["day"] for s in snapshots}
    today = date.today()
    last_day = max(days_seen)
    days_since_last = (today - date.fromisoformat(last_day)).days

    # ── category frequency ────────────────────────────────────────────────────
    cat_counts: Counter = Counter(
        s["category"] for s in snapshots if s.get("category")
    )

    # ── sub_tag frequency ─────────────────────────────────────────────────────
    tag_counts: Counter = Counter()
    for s in snapshots:
        for t in s.get("sub_tags") or []:
            tag_counts[t] += 1

    # ── valence trend (last 7 days, daily avg) ────────────────────────────────
    daily_valence: dict[str, list[float]] = defaultdict(list)
    for s in snapshots:
        if s.get("valence") is not None:
            daily_valence[s["day"]].append(s["valence"])
    sorted_days = sorted(daily_valence)[-7:]
    daily_avg = [sum(daily_valence[d]) / len(daily_valence[d]) for d in sorted_days]

    # ── rule 1: dominant negative category (3+ snapshots) ────────────────────
    _CAT_Q = {
        "stress":   ("Stress",    "You've seemed pretty stressed lately — what's been weighing on you?"),
        "anxiety":  ("Worry",     "It looks like something's been on your mind a lot. Want to talk about it?"),
        "low_mood": ("Low mood",  "You've had some harder days recently — what do you think has been bringing you down?"),
        "anger":    ("Frustration", "You've mentioned feeling frustrated a few times — what's been getting to you?"),
    }
    negative_cats = set(_CAT_Q)
    for cat, cnt in cat_counts.most_common(2):
        if cat in negative_cats and cnt >= 3:
            top_tags = [t for t, _ in tag_counts.most_common(3)]
            query = f"{cat} {' '.join(top_tags)}"
            label, question = _CAT_Q[cat]
            insights.append({
                "type": "pattern",
                "label": label,
                "question": question,
                "rag_query": query,
                "evidence": {"category": cat, "count": cnt, "top_tags": top_tags},
                "priority": 1,
            })
            break

    # ── rule 2: sustained valence decline (3+ consecutive days downward) ──────
    if len(daily_avg) >= 3:
        declines = sum(
            1 for i in range(1, len(daily_avg)) if daily_avg[i] < daily_avg[i - 1]
        )
        if declines >= len(daily_avg) - 1:
            top_cat = cat_counts.most_common(1)[0][0] if cat_counts else "feelings"
            insights.append({
                "type": "trend",
                "label": "Mood shift",
                "question": "Your mood has been drifting downward over the past few days — has something changed?",
                "rag_query": f"feeling down tired {top_cat}",
                "evidence": {"trend": "declining", "days": len(daily_avg), "avg_valence": round(sum(daily_avg) / len(daily_avg), 2)},
                "priority": 2,
            })

    # ── rule 3: high-frequency sub_tag (4+ occurrences) ──────────────────────
    _TAG_Q = {
        "busy":         ("Busy",        "You've been mentioning how busy you are — what's taking up most of your energy?"),
        "exhausted":    ("Exhausted",   "You've seemed really drained lately — is it more physical or emotional?"),
        "overwhelmed":  ("Overwhelmed", "You've brought up feeling overwhelmed a few times — what feels like too much right now?"),
        "worried":      ("Worried",     "It sounds like something's been sitting with you — is it one thing or a few things?"),
        "lonely":       ("Lonely",      "You've mentioned feeling lonely — when does it hit you the hardest?"),
        "happy":        ("Happy moments", "You've had some genuinely good moments lately — what made them feel good?"),
        "content":      ("Contentment", "You've felt pretty settled a few times recently — what brought that on?"),
        "accomplished": ("Accomplished", "You've done some things you're proud of — which one meant the most to you?"),
    }
    for tag, cnt in tag_counts.most_common(3):
        if cnt >= 4 and len(insights) < 4:
            if tag in _TAG_Q:
                label, question = _TAG_Q[tag]
            else:
                label = tag.replace("_", " ").title()
                question = f"You've mentioned feeling \"{tag}\" quite a bit — want to dig into that?"
            insights.append({
                "type": "tag",
                "label": label,
                "question": question,
                "rag_query": tag,
                "evidence": {"tag": tag, "count": cnt},
                "priority": 3,
            })

    # ── rule 4: silence — no entries in 5+ days ───────────────────────────────
    if days_since_last >= 5 and len(insights) < 5:
        insights.append({
            "type": "silence",
            "label": "Where you've been",
            "question": f"It's been {days_since_last} days since your last entry — how have you been?",
            "rag_query": "last time I wrote",
            "evidence": {"days_silent": days_since_last},
            "priority": 4,
        })

    # ── rule 5: notable positive spike ───────────────────────────────────────
    if daily_avg and max(daily_avg) > 0.4 and len(insights) < 5:
        insights.append({
            "type": "positive",
            "label": "Something good",
            "question": "You had a noticeably good stretch recently — what was going on?",
            "rag_query": "felt good happy calm",
            "evidence": {"peak_valence": round(max(daily_avg), 2)},
            "priority": 5,
        })

    # Sort by priority, deduplicate overlapping rag_queries, cap at 4
    insights.sort(key=lambda x: x["priority"])
    seen_queries: set[str] = set()
    deduped: list[dict] = []
    for ins in insights:
        q = ins["rag_query"].split()[0] if ins["rag_query"] else ins["label"]
        if q not in seen_queries:
            seen_queries.add(q)
            deduped.append(ins)
        if len(deduped) == 4:
            break

    # Guarantee at least one topic even with sparse data
    if not deduped:
        deduped.append({
            "type": "pattern",
            "label": "How you've been",
            "question": "How have you actually been feeling lately?",
            "rag_query": "feeling",
            "evidence": {},
            "priority": 99,
        })

    return deduped


_REFLECT_OPEN_SYSTEM = (
    "You are a warm, perceptive journaling companion. "
    "The user just opened their Reflect space. Write ONE greeting sentence — "
    "personal, human, max 20 words. "
    "You are given 1-3 recent journal snippets and optionally what they said last time in Reflect. "
    "Reference something *specific* from the snippets — a feeling, a situation, a word they used. "
    "If you have a last session snippet, weave it in naturally. "
    "Do NOT list topics. Do NOT say 'I noticed' or 'I see'. Do NOT use words like 'patterns' or 'entries'. "
    "Sound like a friend who remembered, not a therapist who analysed. "
    "Output only the single sentence, nothing else."
)


def reflect_open_sync(snapshots: list[dict]) -> dict[str, Any]:
    """
    Analyse recent mood snapshots and return:
      { greeting: str, topics: [{ label, question, rag_query, type }] }
    Topics carry a conversational question shown in the picker.
    Greeting is grounded in actual recent journal content, not just category names.
    """
    from collections import Counter
    import re
    from . import db as _db

    decisions = _decide_insights(snapshots)

    # Fetch a few real recent entries to ground the greeting
    recent_entries = _db.search_entries("", days=7)  # empty query = recency scan
    if not recent_entries:
        recent_entries = _db.search_entries("", days=14)
    snippets = []
    for e in recent_entries[:3]:
        content = (e.get("content") or "").strip()
        if content:
            date = e.get("created_at", "")[:10]
            snippets.append(f"[{date}] {content[:150]}")
    snippets_str = "\n".join(snippets) if snippets else "(no recent entries)"

    # Last reflect session memory
    last = _db.get_last_reflect_summary()
    if last:
        snippet = last["content"][:100].strip()
        last_hint = f'Last Reflect session ({last["created_at"]}): "{snippet}"'
    else:
        last_hint = ""

    user_content = f"Recent journal entries:\n{snippets_str}"
    if last_hint:
        user_content += f"\n\n{last_hint}"

    messages = [
        {"role": "system", "content": _REFLECT_OPEN_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    options = {**_base_options(), "temperature": 0.75, "max_tokens": 50}
    result = _run_complete(messages, options)
    greeting = result.get("reply", "").strip()
    greeting = re.sub(r"^\d+[\.\)]\s*", "", greeting).strip()
    # Strip any surrounding quotes the model might add
    greeting = greeting.strip('"').strip("'")
    if not greeting or result.get("error"):
        if last:
            greeting = "Last time you mentioned something that stuck with me — how have things been since?"
        else:
            greeting = "Good to see you. Want to talk through how things have been?"

    # Build topics: question shown in picker, label used as chat title
    topics = []
    for d in decisions:
        topics.append({
            "label": d["label"],
            "question": d.get("question", d["label"]),
            "rag_query": d["rag_query"],
            "type": d.get("type", "pattern"),
        })
    topics.append({
        "label": "Something else",
        "question": "Something else on my mind",
        "rag_query": "",
        "type": "free",
    })

    return {"greeting": greeting, "topics": topics}


_REFLECT_AGENT_SYSTEM = """\
You are a warm, grounded journaling companion. You are having a reflective conversation with the user about something specific from their recent entries.

You will be given:
- The topic being explored
- Relevant journal entries the user has written (already retrieved for you)
- The conversation so far

Your job:
- Be specific — reference things the user actually wrote, not generalities
- Ask one gentle follow-up question per turn for the first 2 turns
- After they've shared enough, offer a brief warm observation (2-3 sentences), no more questions
- Never give advice unless directly asked
- Keep every reply under 4 sentences
- Sound like a thoughtful friend, not a therapist
"""

# OpenAI-style tool schemas for Cactus function calling
_REFLECT_TOOLS = json.dumps([
    {
        "type": "function",
        "function": {
            "name": "search_my_entries",
            "description": "Search the user's past journal entries for relevant content. Use this to find specific moments, feelings, or events the user has written about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords or phrases to search for in journal entries",
                    },
                    "days": {
                        "type": "integer",
                        "description": "How many days back to search (default 14, max 60)",
                        "default": 14,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mood_stats",
            "description": "Get aggregated mood statistics for the user over recent days: category counts, most frequent emotional tags, and average valence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to include (default 14)",
                        "default": 14,
                    },
                },
                "required": [],
            },
        },
    },
])


def _execute_tool(name: str, args: dict) -> str:
    """Execute a reflect agent tool call and return the result as a string."""
    from . import db as _db
    try:
        if name == "search_my_entries":
            query = str(args.get("query", ""))
            days = int(args.get("days", 14))
            days = min(max(days, 1), 60)
            rows = _db.search_entries(query, days)
            if not rows:
                return "No entries found matching that query."
            lines = []
            for r in rows:
                date = r.get("created_at", "")[:10]
                content = (r.get("content") or "").strip()[:200]
                lines.append(f"[{date}] {content}")
            return "\n".join(lines)
        elif name == "get_mood_stats":
            days = int(args.get("days", 14))
            days = min(max(days, 1), 60)
            stats = _db.get_mood_stats_for_agent(days)
            return json.dumps(stats)
        else:
            return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Tool error: {exc}"


def _parse_tool_call_content(content: str) -> list[dict] | None:
    """
    Parse tool calls from assistant message content.
    Cactus may encode them as <|tool_call_start|>...<|tool_call_end|>
    or return them in the function_calls list from the JSON result.
    Returns list of {name, arguments} or None.
    """
    calls = []
    import re
    # Try special tokens format
    pattern = r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>"
    matches = re.findall(pattern, content, re.DOTALL)
    for match in matches:
        match = match.strip()
        # Could be: name({"key": "val"}) or JSON: {"name": ..., "arguments": ...}
        try:
            parsed = json.loads(match)
            calls.append({
                "name": parsed.get("name", ""),
                "arguments": parsed.get("arguments", {}),
            })
            continue
        except json.JSONDecodeError:
            pass
        # Try name({...}) format
        fn_match = re.match(r"(\w+)\s*\((.+)\)$", match, re.DOTALL)
        if fn_match:
            fn_name = fn_match.group(1)
            try:
                fn_args = json.loads(fn_match.group(2))
                calls.append({"name": fn_name, "arguments": fn_args})
            except json.JSONDecodeError:
                calls.append({"name": fn_name, "arguments": {}})
    return calls if calls else None


def _run_tool_loop(
    messages: list[dict],
    token_queue: "queue.Queue[str | None]",
    options_tool: dict,
    options_reply: dict,
    max_tool_rounds: int = 3,
) -> dict[str, Any]:
    """
    Core tool-use loop shared by reflect_agent_sync and future callers.

    Phase A — tool rounds (non-streaming, tools enabled):
      Call cactus_complete with _REFLECT_TOOLS up to max_tool_rounds times.
      Each time function_calls are returned, execute tools, inject results,
      and emit "\x00TOOL:<label>\x00" sentinels into token_queue for the frontend.
      Stop as soon as a round returns no function_calls.

    Phase B — reply round (streaming, no tools):
      Once tool calls are exhausted (or never fired), run one final streaming
      completion without tools_json so the model cannot defer again.
      Tokens go directly into token_queue; None sentinel ends the stream.

    Returns { reply, meta } or { error }.
    """
    cactus_complete, _, cactus_get_last_error, model = _get_model()

    # ── Phase A: tool-use rounds ──────────────────────────────────────────────
    for _ in range(max_tool_rounds):
        try:
            with _lock:
                raw = cactus_complete(
                    model,
                    json.dumps(messages),
                    json.dumps(options_tool),
                    _REFLECT_TOOLS,
                    None,  # no streaming in tool rounds
                )
        except Exception as exc:
            token_queue.put(None)
            return {"error": str(exc)}

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            break  # unparseable → skip to reply phase

        if not result.get("success"):
            err = result.get("error") or cactus_get_last_error() or "tool_round_failed"
            token_queue.put(None)
            return {"error": str(err)}

        response_text = result.get("response") or ""

        # Collect function calls from structured output or inline tokens
        fn_calls = list(result.get("function_calls") or [])
        if not fn_calls and response_text:
            inline = _parse_tool_call_content(response_text)
            if inline:
                fn_calls = inline

        if not fn_calls:
            # Model chose not to call tools — skip to reply phase
            break

        # Inject assistant tool-call turn
        messages.append({"role": "assistant", "content": response_text})

        for fc in fn_calls:
            fn_name = fc.get("name", "")
            fn_args = fc.get("arguments", {})
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}

            # Emit step indicator to frontend before executing
            label = f"🔍 {fn_name.replace('_', ' ').title()}…"
            token_queue.put(f"\x00TOOL:{label}\x00")

            tool_result = _execute_tool(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "content": json.dumps({"name": fn_name, "content": tool_result}),
            })

    # ── Phase B: final streaming reply (tools disabled) ───────────────────────
    full_reply: list[str] = []

    def _on_token(token_str: str, _token_id: int) -> None:
        if token_str:
            token_queue.put(token_str)
            full_reply.append(token_str)

    try:
        with _lock:
            raw = cactus_complete(
                model,
                json.dumps(messages),
                json.dumps(options_reply),
                None,       # no tools — force direct reply
                _on_token,
            )
    except Exception as exc:
        token_queue.put(None)
        return {"error": str(exc)}

    token_queue.put(None)

    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"reply": "".join(full_reply)}

    if not result.get("success"):
        return {"error": result.get("error") or "completion_failed"}

    reply = "".join(full_reply) or (result.get("response") or "")
    meta = {k: result[k] for k in (
        "time_to_first_token_ms", "total_time_ms", "decode_tps", "total_tokens"
    ) if k in result}
    return {"reply": reply, "meta": meta} if meta else {"reply": reply}


def reflect_agent_sync(
    topic_label: str,
    topic_question: str,
    rag_query: str,
    history: list[dict],
    token_queue: "queue.Queue[str | None]",
) -> dict[str, Any]:
    """
    Agentic reflect conversation turn.

    On every turn, retrieved journal entries are injected directly into the
    system prompt — no synthetic tool exchange, no dependency on the model
    knowing a specific tool-call token format.

    On subsequent turns the tool loop can optionally call search_my_entries
    or get_mood_stats for additional context.
    """
    # ── Retrieve relevant entries upfront (always, not just first turn) ───────
    query = rag_query or topic_label
    token_queue.put(f"\x00TOOL:🔍 Looking through your entries…\x00")
    retrieved = _execute_tool("search_my_entries", {"query": query, "days": 14})

    # Build system with injected context — model-agnostic, always works
    system_content = (
        f"{_REFLECT_AGENT_SYSTEM}\n\n"
        f"Topic being explored: {topic_label}\n"
        f"Opening question: {topic_question}\n\n"
        f"Relevant journal entries (retrieved):\n{retrieved}"
    )

    messages: list[dict] = [{"role": "system", "content": system_content}] + list(history)

    options_tool  = {**_base_options(), "temperature": 0.3, "max_tokens": 80}
    options_reply = {**_base_options(), "temperature": 0.7, "max_tokens": 300}

    return _run_tool_loop(messages, token_queue, options_tool, options_reply)


def shutdown_model() -> None:
    global _model, _weights_used
    with _lock:
        if _model is None:
            return
        try:
            _, _, cactus_destroy, _, _ = _load_cactus()
            cactus_destroy(_model)
        finally:
            _model = None
            _weights_used = None

