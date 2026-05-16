"""Mood extraction and insights copy (stubbed model)."""

import json

import pytest
import app.emotion as emotion


def _stub_complete(monkeypatch, replies: list[str]):
    calls = {"n": 0}

    def _fake(messages, options, pcm_data=None):
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        return {"reply": reply}

    monkeypatch.setattr(emotion, "_run_complete", _fake)
    return calls


def test_extract_emotion_for_journal_tagging(monkeypatch):
    payload = json.dumps({
        "valence": -0.5, "intensity": 0.8,
        "category": "stress", "sub_tags": ["busy"],
    })
    _stub_complete(monkeypatch, [payload])
    result = emotion.extract_emotion_sync("Too much to do today.")
    assert result["category"] == "stress" and "error" not in result


def test_tone_and_insights_narrative(monkeypatch):
    _stub_complete(monkeypatch, ["Calm week with busy stretches."])
    tone = emotion.tone_summary_sync("voice transcript here")
    assert tone

    narrative = emotion.insight_narrative_sync({
        "daily": [{"day": "2026-04-01", "valence": 0.2, "intensity": 0.5, "count": 1}],
        "tags": [{"tag": "busy", "count": 2}],
        "categories": [{"category": "stress", "count": 1}],
    })
    assert narrative
