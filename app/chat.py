"""
Chat streaming — plain conversational chat via Cactus.
"""

from __future__ import annotations

import json
import queue
from typing import Any

from .engine import _get_model, _base_options, _lock

_SYSTEM_PROMPT = (
    "You are a warm, private companion for an emotion journal. "
    "The user shares personal feelings with you. "
    "Listen carefully, respond with empathy and gentle reflection. "
    "Keep responses concise (2-4 sentences). "
    "Never diagnose or treat medical or psychiatric conditions. "
    "If the user seems in crisis, gently suggest professional support."
)


def chat_stream_sync(
    user_text: str,
    history: list[dict] | None,
    token_queue: "queue.Queue[str | None]",
    pcm_data: bytes | None = None,
) -> dict[str, Any]:
    """
    Stream tokens into ``token_queue`` as they're produced.
    Pass pcm_data (PCM int16 raw bytes) to send audio directly to Gemma 4.
    Puts ``None`` as a sentinel when generation finishes (or on error).
    Returns meta dict (reply is empty string; caller reconstructs from queue).
    """
    cactus_complete, _, _, model = _get_model()

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

    try:
        with _lock:
            raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, _on_token, pcm_data)
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
