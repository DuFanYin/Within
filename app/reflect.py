"""
Reflect agent — insight detection, opening sequence, agentic conversation.
"""

from __future__ import annotations

import json
import queue
import re
from typing import Any

from .engine import _base_options, _run_complete, _get_model, _lock, rag_query

# ── Tool schemas ──────────────────────────────────────────────────────────────

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


# ── Insight decision layer ────────────────────────────────────────────────────

def _decide_insights(snapshots: list[dict]) -> list[dict]:
    """
    Pure-code decision layer. Takes recent mood snapshots and returns up to 5
    insight descriptors. No LLM involved here.
    """
    from collections import Counter, defaultdict
    from datetime import date

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

    days_seen: set[str] = {s["day"] for s in snapshots}
    today = date.today()
    last_day = max(days_seen)
    days_since_last = (today - date.fromisoformat(last_day)).days

    cat_counts: Counter = Counter(
        s["category"] for s in snapshots if s.get("category")
    )

    tag_counts: Counter = Counter()
    for s in snapshots:
        for t in s.get("sub_tags") or []:
            tag_counts[t] += 1

    daily_valence: dict[str, list[float]] = defaultdict(list)
    for s in snapshots:
        if s.get("valence") is not None:
            daily_valence[s["day"]].append(s["valence"])
    sorted_days = sorted(daily_valence)[-7:]
    daily_avg = [sum(daily_valence[d]) / len(daily_valence[d]) for d in sorted_days]

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

    if days_since_last >= 5 and len(insights) < 5:
        insights.append({
            "type": "silence",
            "label": "Where you've been",
            "question": f"It's been {days_since_last} days since your last entry — how have you been?",
            "rag_query": "last time I wrote",
            "evidence": {"days_silent": days_since_last},
            "priority": 4,
        })

    if daily_avg and max(daily_avg) > 0.4 and len(insights) < 5:
        insights.append({
            "type": "positive",
            "label": "Something good",
            "question": "You had a noticeably good stretch recently — what was going on?",
            "rag_query": "felt good happy calm",
            "evidence": {"peak_valence": round(max(daily_avg), 2)},
            "priority": 5,
        })

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


# ── Tool execution ────────────────────────────────────────────────────────────

def _rag_search(query: str) -> str:
    """Vector search via Cactus RAG."""
    if not query.strip():
        return "No query provided."

    try:
        results = rag_query(query, top_k=6)
    except Exception:
        results = []

    lines = []
    for r in results:
        doc = (r.get("document") or r.get("text") or r.get("content") or "").strip()
        if doc:
            lines.append(doc[:300])

    return "\n\n".join(lines) if lines else "No relevant entries found."


def _execute_tool(name: str, args: dict) -> str:
    """Execute a reflect agent tool call and return the result as a string."""
    from . import db as _db
    try:
        if name == "search_my_entries":
            query = str(args.get("query", ""))
            return _rag_search(query)
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
    Handles <|tool_call_start|>...<|tool_call_end|> and name({...}) formats.
    """
    calls = []
    pattern = r"<\|tool_call_start\|>(.*?)<\|tool_call_end\|>"
    matches = re.findall(pattern, content, re.DOTALL)
    for match in matches:
        match = match.strip()
        try:
            parsed = json.loads(match)
            calls.append({
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
                calls.append({"name": fn_name, "arguments": fn_args})
            except json.JSONDecodeError:
                calls.append({"name": fn_name, "arguments": {}})
    return calls if calls else None


# ── Tool loop ─────────────────────────────────────────────────────────────────

def _run_tool_loop(
    messages: list[dict],
    token_queue: "queue.Queue[str | None]",
    options_tool: dict,
    options_reply: dict,
    max_tool_rounds: int = 3,
) -> dict[str, Any]:
    """
    Phase A: tool rounds (non-streaming, tools enabled) up to max_tool_rounds.
    Phase B: final streaming reply (tools disabled).
    """
    cactus_complete, _, cactus_get_last_error, model = _get_model()

    for _ in range(max_tool_rounds):
        try:
            with _lock:
                raw = cactus_complete(
                    model,
                    json.dumps(messages),
                    json.dumps(options_tool),
                    _REFLECT_TOOLS,
                    None,
                )
        except Exception as exc:
            token_queue.put(None)
            return {"error": str(exc)}

        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            break

        if not result.get("success"):
            err = result.get("error") or cactus_get_last_error() or "tool_round_failed"
            token_queue.put(None)
            return {"error": str(err)}

        response_text = result.get("response") or ""

        fn_calls = list(result.get("function_calls") or [])
        if not fn_calls and response_text:
            inline = _parse_tool_call_content(response_text)
            if inline:
                fn_calls = inline

        if not fn_calls:
            break

        messages.append({"role": "assistant", "content": response_text})

        for fc in fn_calls:
            fn_name = fc.get("name", "")
            fn_args = fc.get("arguments", {})
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}

            label = f"🔍 {fn_name.replace('_', ' ').title()}…"
            token_queue.put(f"\x00TOOL:{label}\x00")

            tool_result = _execute_tool(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "content": json.dumps({"name": fn_name, "content": tool_result}),
            })

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
                None,
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


# ── Public API ────────────────────────────────────────────────────────────────

def reflect_open_sync(snapshots: list[dict]) -> dict[str, Any]:
    """
    Analyse recent mood snapshots and return:
      { greeting: str, topics: [{ label, question, rag_query, type }] }
    """
    from . import db as _db

    decisions = _decide_insights(snapshots)

    # Use the top insight's rag_query for semantic retrieval; fall back to recency
    greeting_query = decisions[0]["rag_query"] if decisions else "feeling"
    try:
        rag_results = rag_query(greeting_query, top_k=3) if greeting_query.strip() else []
    except Exception:
        rag_results = []

    snippets = []
    if rag_results:
        for r in rag_results:
            doc = (r.get("document") or r.get("text") or r.get("content") or "").strip()
            if not doc:
                continue
            m = re.match(r'\[(\d{4}-\d{2}-\d{2})\]', doc)
            date = m.group(1) if m else ""
            content = re.sub(r'^\[.*?\]\s*(\[.*?\]\s*)?', '', doc).strip()[:150]
            if content:
                snippets.append(f"[{date}] {content}" if date else content)

    snippets_str = "\n".join(snippets) if snippets else "(no recent entries)"

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
    greeting = greeting.strip('"').strip("'")
    if not greeting or result.get("error"):
        if last:
            greeting = "Last time you mentioned something that stuck with me — how have things been since?"
        else:
            greeting = "Good to see you. Want to talk through how things have been?"

    topics = []
    for d in decisions:
        topics.append({
            "label": d["label"],
            "question": d.get("question", d["label"]),
            "rag_query": d["rag_query"],
            "type": d.get("type", "pattern"),
        })
    topics.append({
        "label": "Just talk",
        "question": "Just talk — no topic, whatever's on my mind",
        "rag_query": "",
        "type": "just_chat",
    })

    return {"greeting": greeting, "topics": topics}


def reflect_agent_sync(
    topic_label: str,
    topic_question: str,
    rag_query: str,
    history: list[dict],
    token_queue: "queue.Queue[str | None]",
) -> dict[str, Any]:
    """
    Agentic reflect conversation turn. Retrieves relevant entries upfront,
    injects them into system prompt, then runs the tool loop.
    """
    query = rag_query or topic_label
    token_queue.put(f"\x00TOOL:🔍 Looking through your entries…\x00")
    retrieved = _rag_search(query)

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
