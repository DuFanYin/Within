"""
Tests for app/emotion.py — emotion extraction schema validation, retry logic,
value clamping. Stubs _run_complete so no Cactus/Gemma 4 required.
"""

import json
import pytest
import app.emotion as emotion
import app.engine as engine


def _patch_complete(monkeypatch, replies: list[str]):
    """
    Make _run_complete return successive replies from the list.
    Must patch on the emotion module's reference (imported name), not engine.
    """
    call_count = {"n": 0}

    def _stub(messages, options, pcm_data=None):
        idx = min(call_count["n"], len(replies) - 1)
        call_count["n"] += 1
        return {"reply": replies[idx]}

    monkeypatch.setattr(emotion, "_run_complete", _stub)
    return call_count


# ── happy path ────────────────────────────────────────────────────────────────

def test_extract_positive_entry(monkeypatch):
    payload = json.dumps({"valence": 0.7, "intensity": 0.6, "category": "positive", "sub_tags": ["happy", "content"]})
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("Today was a great day, I felt happy and at ease.")
    assert result["category"] == "positive"
    assert result["valence"] > 0
    assert "happy" in result["sub_tags"]
    assert "error" not in result


def test_extract_stress_entry(monkeypatch):
    payload = json.dumps({"valence": -0.5, "intensity": 0.8, "category": "stress", "sub_tags": ["busy", "drained"]})
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("Too much to do, completely drained.")
    assert result["category"] == "stress"
    assert result["valence"] < 0
    assert "error" not in result


def test_extract_all_six_categories(monkeypatch):
    for cat, sub in [
        ("positive", "happy"),
        ("stress", "busy"),
        ("anxiety", "worried"),
        ("low_mood", "sad"),
        ("anger", "angry"),
        ("social", "lonely"),
    ]:
        payload = json.dumps({"valence": 0.0, "intensity": 0.5, "category": cat, "sub_tags": [sub]})
        _patch_complete(monkeypatch, [payload])
        result = emotion.extract_emotion_sync("test")
        assert result["category"] == cat, f"Category {cat} not extracted"
        assert "error" not in result


# ── sub_tag validation ────────────────────────────────────────────────────────

def test_extract_sub_tags_filtered_to_valid(monkeypatch):
    payload = json.dumps({
        "valence": 0.5, "intensity": 0.5, "category": "positive",
        "sub_tags": ["happy", "invalid_tag", "content"]
    })
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("good day")
    assert "invalid_tag" not in result["sub_tags"]
    assert "happy" in result["sub_tags"]
    assert "content" in result["sub_tags"]


def test_extract_sub_tags_max_three(monkeypatch):
    payload = json.dumps({
        "valence": 0.5, "intensity": 0.5, "category": "stress",
        "sub_tags": ["busy", "exhausted", "overwhelmed", "drained"]
    })
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("overwhelming week")
    assert len(result["sub_tags"]) <= 3


# ── value clamping ────────────────────────────────────────────────────────────

def test_valence_clamped_above(monkeypatch):
    payload = json.dumps({"valence": 2.5, "intensity": 0.5, "category": "positive", "sub_tags": ["happy"]})
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("amazing")
    assert result["valence"] == 1.0


def test_valence_clamped_below(monkeypatch):
    payload = json.dumps({"valence": -3.0, "intensity": 0.5, "category": "low_mood", "sub_tags": ["sad"]})
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("terrible")
    assert result["valence"] == -1.0


def test_intensity_clamped(monkeypatch):
    payload = json.dumps({"valence": 0.0, "intensity": 5.0, "category": "stress", "sub_tags": ["busy"]})
    _patch_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("busy")
    assert result["intensity"] == 1.0


# ── retry logic ───────────────────────────────────────────────────────────────

def test_retry_on_bad_json_succeeds_second(monkeypatch):
    good = json.dumps({"valence": 0.3, "intensity": 0.4, "category": "positive", "sub_tags": ["content"]})
    calls = _patch_complete(monkeypatch, ["not json at all", good])
    result = emotion.extract_emotion_sync("decent day")
    assert result["category"] == "positive"
    assert calls["n"] == 2


def test_both_retries_fail_returns_error(monkeypatch):
    _patch_complete(monkeypatch, ["bad json", "also bad"])
    result = emotion.extract_emotion_sync("test")
    assert result.get("error") == "parse_failed"
    assert result["valence"] is None
    assert result["sub_tags"] == []


def test_invalid_category_retries(monkeypatch):
    bad = json.dumps({"valence": 0.5, "intensity": 0.5, "category": "UNKNOWN", "sub_tags": []})
    good = json.dumps({"valence": 0.5, "intensity": 0.5, "category": "positive", "sub_tags": ["happy"]})
    calls = _patch_complete(monkeypatch, [bad, good])
    result = emotion.extract_emotion_sync("ok day")
    assert result["category"] == "positive"
    assert calls["n"] == 2


# ── markdown stripping ────────────────────────────────────────────────────────

def test_strips_markdown_code_fence(monkeypatch):
    raw = "```json\n" + json.dumps({"valence": 0.2, "intensity": 0.3, "category": "positive", "sub_tags": ["relaxed"]}) + "\n```"
    _patch_complete(monkeypatch, [raw])
    result = emotion.extract_emotion_sync("nice day")
    assert result["category"] == "positive"
    assert "error" not in result


# ── tone_summary & insight_narrative shape ────────────────────────────────────

def test_tone_summary_returns_string(monkeypatch):
    _patch_complete(monkeypatch, ["The speaker sounds calm and reflective."])
    result = emotion.tone_summary_sync("I went for a walk today.")
    assert isinstance(result, str) and len(result) > 0


def test_insight_narrative_returns_string(monkeypatch):
    _patch_complete(monkeypatch, ["You had a thoughtful week. You mentioned feeling busy several times. Keep going."])
    stats = {
        "daily": [{"day": "2026-04-01", "valence": 0.3, "intensity": 0.5, "count": 2}],
        "tags": [{"tag": "busy", "count": 3}],
        "categories": [{"category": "stress", "count": 2}],
    }
    result = emotion.insight_narrative_sync(stats)
    assert isinstance(result, str) and len(result) > 0


def test_insight_narrative_empty_stats(monkeypatch):
    result = emotion.insight_narrative_sync({"daily": [], "tags": [], "categories": []})
    assert result == ""
