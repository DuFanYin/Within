"""Reflect topic picker (_decide_insights) — pure Python, no model."""

from datetime import date, timedelta

from app.reflect import _decide_insights


def _snap(day_offset=0, category="positive", valence=0.5, tags=None):
    return {
        "day": (date.today() - timedelta(days=day_offset)).isoformat(),
        "category": category,
        "valence": valence,
        "intensity": 0.5,
        "sub_tags": tags or [],
    }


def test_no_entries_suggests_silence_topic():
    topics = _decide_insights([])
    assert len(topics) == 1 and topics[0]["type"] == "silence"


def test_repeated_stress_yields_pattern_topic():
    snaps = [_snap(i, category="stress", valence=-0.4, tags=["busy"]) for i in range(4)]
    topics = _decide_insights(snaps)
    assert any(t["type"] == "pattern" for t in topics)
    for t in topics:
        assert t.get("label") and t.get("rag_query") is not None and t.get("type")
