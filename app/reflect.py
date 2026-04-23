"""
Reflect — insight detection and opening sequence.
"""

from __future__ import annotations

import re
from typing import Any

from .engine import _base_options, _run_complete, rag_query

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


# ── Public API ────────────────────────────────────────────────────────────────

def reflect_open_sync(snapshots: list[dict]) -> dict[str, Any]:
    """
    Analyse recent mood snapshots and return:
      { greeting: str, topics: [{ label, question, rag_query, type }] }
    """
    from . import db as _db

    decisions = _decide_insights(snapshots)

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
