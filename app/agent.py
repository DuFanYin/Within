"""
Companion agent — single agentic loop for all conversation turns.
"""

from __future__ import annotations

import base64
import json
import queue
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from . import engine as _engine
from .engine import _base_options, _get_model, _lock, rag_query

_COMPANION_SYSTEM = """\
You are a warm, private companion for someone's emotion journal. Everything stays on their device.

You have tools to search their past entries and check their mood patterns — use them when they'd
help you give a more grounded, specific response. You don't need to use tools every turn.

When you do reference past entries, be specific: quote or paraphrase what they wrote.
When you don't have relevant history, just listen and respond warmly.

Rules:
- At most one question per turn. Zero questions is fine.
- Never give advice unless directly asked.
- Keep replies under 4 sentences.
- Never diagnose or suggest clinical terms.
- If they seem in crisis, gently mention professional support.
- Sound like a thoughtful friend, not a therapist running a session.\
"""

_COMPANION_TOOLS = json.dumps([
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


def companion_agent_sync(
    message: str,
    history: list[dict],
    mood_snapshots: list[dict],
    token_queue: "queue.Queue[str | None]",
    pcm_data: bytes | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> dict[str, Any]:
    """
    Single agentic loop for all companion conversation turns.

    Phase A: tool rounds (non-streaming, temperature=0.2) — LLM decides when to call tools.
    Phase B: final streaming reply (temperature=0.7, pcm_data passed here if present).
    """
    try:
        cactus_complete, _, cactus_get_last_error, _ = _get_model()

        system_content = _COMPANION_SYSTEM
        if mood_snapshots:
            from collections import Counter
            cat_counts: Counter = Counter(
                s["category"] for s in mood_snapshots if s.get("category")
            )
            tag_counts: Counter = Counter()
            for s in mood_snapshots:
                for t in s.get("sub_tags") or []:
                    tag_counts[t] += 1
            valences = [s["valence"] for s in mood_snapshots if s.get("valence") is not None]
            avg_v = round(sum(valences) / len(valences), 2) if valences else None
            dominant = cat_counts.most_common(1)[0][0] if cat_counts else None
            top_tags = [t for t, _ in tag_counts.most_common(3)]
            parts = []
            if dominant:
                parts.append(f"mostly {dominant}")
            if avg_v is not None:
                parts.append(f"avg valence {avg_v:+.2f}")
            if top_tags:
                parts.append(f"top tags: {', '.join(top_tags)}")
            if parts:
                system_content = f"{_COMPANION_SYSTEM}\n\n[Recent mood context — last 7 days]\n{'; '.join(parts)}"

        messages: list[dict] = [{"role": "system", "content": system_content}]
        messages.extend(history)
        if image_bytes and image_mime:
            b64 = base64.b64encode(image_bytes).decode()
            user_content: str | list = [
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64}"}},
                {"type": "text", "text": message or "What do you notice in this photo?"},
            ]
        else:
            user_content = message
        messages.append({"role": "user", "content": user_content})

        options_tool  = {**_base_options(), "temperature": 0.2, "max_tokens": 80}
        options_reply = {**_base_options(), "temperature": 0.7, "max_tokens": 300}

        for _ in range(3):
            with _lock:
                model = _engine._model
                if not model:
                    return {"error": "model not loaded"}
                raw = cactus_complete(
                    model,
                    json.dumps(messages),
                    json.dumps(options_tool),
                    _COMPANION_TOOLS,
                    None,
                )

            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                break

            if not result.get("success"):
                err = result.get("error") or cactus_get_last_error() or "tool_round_failed"
                return {"error": str(err)}

            response_text = result.get("response") or ""

            fn_calls = list(result.get("function_calls") or [])
            if not fn_calls and response_text:
                for match in re.findall(
                    r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>", response_text, re.DOTALL
                ):
                    match = match.strip()
                    try:
                        parsed = json.loads(match)
                        fn_calls.append({
                            "name": parsed.get("name", ""),
                            "arguments": parsed.get("arguments", {}),
                        })
                        continue
                    except json.JSONDecodeError:
                        pass
                    fn_match = re.match(r"(\w+)\s*\((.+)\)$", match, re.DOTALL)
                    if fn_match:
                        fn_name = fn_match.group(1)
                        try:
                            fn_args = json.loads(fn_match.group(2))
                        except json.JSONDecodeError:
                            fn_args = {}
                        fn_calls.append({"name": fn_name, "arguments": fn_args})

            if not fn_calls:
                break

            messages.append({"role": "assistant", "content": response_text})

            for fc in fn_calls:
                fn_name = fc.get("name", "")
                fn_args = fc.get("arguments", {})
                if isinstance(fn_args, str):
                    fn_args = json.loads(fn_args)

                token_queue.put(f"\x00TOOL:🔍 {fn_name.replace('_', ' ').title()}…\x00")

                from . import db as _db
                if fn_name == "search_my_entries":
                    days = min(max(int(fn_args.get("days", 14)), 1), 60)
                    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
                    lines = []
                    for r in rag_query(str(fn_args.get("query", "")), top_k=6):
                        doc = (r.get("document") or r.get("text") or r.get("content") or "").strip()
                        if doc.startswith("[") and len(doc) >= 11:
                            doc_date = datetime.strptime(doc[1:11], "%Y-%m-%d").date()
                            if doc_date < cutoff:
                                continue
                        if doc:
                            lines.append(doc[:300])
                    tool_result = "\n\n".join(lines) if lines else "No relevant entries found."
                elif fn_name == "get_mood_stats":
                    days = min(max(int(fn_args.get("days", 14)), 1), 60)
                    tool_result = json.dumps(_db.get_mood_stats_for_agent(days))
                else:
                    tool_result = f"Unknown tool: {fn_name}"

                messages.append({
                    "role": "tool",
                    "content": json.dumps({"name": fn_name, "content": tool_result}),
                })

        full_reply: list[str] = []

        def _on_token(token_str: str, _token_id: int) -> None:
            if token_str:
                token_queue.put(token_str)
                full_reply.append(token_str)

        with _lock:
            model = _engine._model
            if not model:
                return {"error": "model not loaded"}
            raw = cactus_complete(
                model,
                json.dumps(messages),
                json.dumps(options_reply),
                None,
                _on_token,
                pcm_data,
            )

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
    finally:
        token_queue.put(None)
