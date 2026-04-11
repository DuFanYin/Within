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
        fname.write_text(
            f"[{date}] [{mode}]\n{e['content']}\n",
            encoding="utf-8",
        )
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


def _run_complete(messages: list[dict], options: dict) -> dict[str, Any]:
    cactus_complete, _, cactus_get_last_error, model = _get_model()
    with _lock:
        raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, None)
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
) -> dict[str, Any]:
    """
    Like chat_sync but streams tokens into ``token_queue`` as they're produced.
    Puts ``None`` as a sentinel when generation finishes (or on error).
    Returns the same meta dict as chat_sync (reply is empty string; caller
    reconstructs the full reply from the queue).
    """
    cactus_complete, _, _, model = _get_model()

    messages = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + (history or [])
        + [{"role": "user", "content": user_text}]
    )
    options = _base_options()

    def _on_token(token_str: str, _token_id: int) -> None:
        if token_str:
            token_queue.put(token_str)

    cb = _on_token

    try:
        with _lock:
            raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, cb)
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


def chat_sync(user_text: str, history: list[dict] | None = None) -> dict[str, Any]:
    """
    Multi-turn chat. ``history`` is a list of {role, content} dicts
    (earlier messages first, NOT including the current user_text).
    """
    messages = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + (history or [])
        + [{"role": "user", "content": user_text}]
    )
    return _run_complete(messages, _base_options())


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


def reflect_stream_sync(
    question: str,
    token_queue: "queue.Queue[str | None]",
) -> dict[str, Any]:
    """Streaming version of reflect_sync. Puts tokens into token_queue, None as sentinel."""
    cactus_complete, _, cactus_get_last_error, model = _get_model()

    messages = [
        {
            "role": "system",
            "content": (
                "You are a thoughtful, empathetic journaling companion with access to the user's past journal entries. "
                "Answer the user's reflective question based only on what they have shared before. "
                "Be warm and specific — reference actual feelings or moments from their entries when relevant. "
                "If the entries don't contain enough information, say so gently. "
                "Keep the response to 4-6 sentences."
            ),
        },
        {"role": "user", "content": question},
    ]
    options = {**_base_options(), "temperature": 0.6, "max_tokens": 300}

    def _on_token(token_str: str, _token_id: int) -> None:
        if token_str:
            token_queue.put(token_str)

    try:
        with _lock:
            raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, _on_token)
    except Exception as exc:
        token_queue.put(None)
        return {"error": str(exc), "reply": ""}

    token_queue.put(None)

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


def reflect_sync(question: str) -> dict[str, Any]:
    """
    Answer a reflective question about the user's past journal entries using RAG.
    The corpus index must be loaded (cactus_init with corpus_dir).
    inject_rag_context fires automatically inside cactus_complete.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a thoughtful, empathetic journaling companion with access to the user's past journal entries. "
                "Answer the user's reflective question based only on what they have shared before. "
                "Be warm and specific — reference actual feelings or moments from their entries when relevant. "
                "If the entries don't contain enough information, say so gently. "
                "Keep the response to 4-6 sentences."
            ),
        },
        {"role": "user", "content": question},
    ]
    options = {**_base_options(), "temperature": 0.6, "max_tokens": 300}
    return _run_complete(messages, options)


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

