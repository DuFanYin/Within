"""
Emotion extraction, summarization, tone analysis, and image captioning.
"""

from __future__ import annotations

import json
from typing import Any

from .engine import _base_options, _run_complete

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
    Generate a short emotional/contextual caption for an image.
    Returns a 2-3 sentence description for RAG indexing, or empty string on failure.
    """
    import base64
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError:
        return ""

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
    Generate a tone/expressiveness summary for a voice transcript.
    Returns a short paragraph describing how the person spoke, or empty string on failure.
    """
    messages = [
        {"role": "system", "content": _TONE_SYSTEM},
        {"role": "user", "content": transcript},
    ]
    options = {**_base_options(), "temperature": 0.5, "max_tokens": 150}
    result = _run_complete(messages, options)
    return result.get("reply", "").strip()


_NARRATIVE_SYSTEM = (
    "You are a warm, perceptive journaling companion writing a brief weekly reflection for the user. "
    "You are given structured mood data: entry counts, dominant emotional categories, valence trends, and frequent tags. "
    "Write exactly 3 sentences in second person (You…). "
    "Sentence 1: what you noticed about their week (entry volume + dominant emotion). "
    "Sentence 2: one specific detail — a tag that kept appearing, a mood shift, or a pattern. "
    "Sentence 3: something gently forward-looking or affirming — not advice, just warmth. "
    "Do not use bullet points, headers, or lists. No clinical language. Sound like a thoughtful friend."
)


def insight_narrative_sync(stats: dict) -> str:
    """
    Generate a 3-sentence weekly narrative from aggregated mood stats.
    stats = { daily, tags, categories } from get_stats().
    Returns a string, or empty string on failure.
    """
    daily = stats.get("daily", [])
    categories = stats.get("categories", [])
    tags = stats.get("tags", [])

    if not daily and not categories:
        return ""

    # Build a compact text summary to feed the LLM
    from datetime import date, timedelta
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    recent = [d for d in daily if d["day"] >= week_ago]
    total_recent = sum(d["count"] for d in recent)
    total_all = sum(d["count"] for d in daily)

    valences = [d["valence"] for d in recent if d.get("valence") is not None]
    avg_valence = round(sum(valences) / len(valences), 2) if valences else None

    top_cat = categories[0]["category"].replace("_", " ") if categories else None
    top_tags = [t["tag"].replace("_", " ") for t in tags[:3]]

    # Trend: compare first half vs second half of recent days
    trend = "stable"
    if len(valences) >= 4:
        mid = len(valences) // 2
        if sum(valences[mid:]) / (len(valences) - mid) > sum(valences[:mid]) / mid + 0.1:
            trend = "improving"
        elif sum(valences[mid:]) / (len(valences) - mid) < sum(valences[:mid]) / mid - 0.1:
            trend = "declining"

    summary_lines = [
        f"Entries this week: {total_recent} (total logged: {total_all})",
        f"Dominant emotion: {top_cat}" if top_cat else "",
        f"Average mood valence: {avg_valence} (trend: {trend})" if avg_valence is not None else "",
        f"Most frequent feelings: {', '.join(top_tags)}" if top_tags else "",
    ]
    summary = "\n".join(l for l in summary_lines if l)

    messages = [
        {"role": "system", "content": _NARRATIVE_SYSTEM},
        {"role": "user", "content": summary},
    ]
    options = {**_base_options(), "temperature": 0.7, "max_tokens": 120}
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
