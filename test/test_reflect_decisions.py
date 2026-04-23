"""
Tests for the pure-Python reflect decision layer: _decide_insights.
No stubs needed — no LLM or DB calls.
"""

from datetime import date, timedelta
import pytest
from app.reflect import _decide_insights


def _snap(day_offset=0, category="positive", valence=0.5, tags=None):
    """Build a mood snapshot dict relative to today."""
    day = (date.today() - timedelta(days=day_offset)).isoformat()
    return {
        "day": day,
        "category": category,
        "valence": valence,
        "intensity": 0.5,
        "sub_tags": tags or [],
    }


# ── empty / no data ───────────────────────────────────────────────────────────

def test_no_snapshots_returns_silence():
    result = _decide_insights([])
    assert len(result) == 1
    assert result[0]["type"] == "silence"


# ── pattern detection ─────────────────────────────────────────────────────────

def test_stress_pattern_detected():
    snaps = [_snap(i, category="stress", valence=-0.4, tags=["busy"]) for i in range(4)]
    result = _decide_insights(snaps)
    types = [t["type"] for t in result]
    assert "pattern" in types


def test_anxiety_pattern_detected():
    snaps = [_snap(i, category="anxiety", valence=-0.3, tags=["worried"]) for i in range(3)]
    result = _decide_insights(snaps)
    labels = [t["label"] for t in result]
    assert any("worry" in l.lower() or "anxiety" in l.lower() for l in labels)


def test_negative_pattern_needs_at_least_three():
    snaps = [_snap(i, category="stress", valence=-0.4) for i in range(2)]
    result = _decide_insights(snaps)
    # Only count real pattern detections, not the fallback "How you've been" catch-all
    pattern_topics = [t for t in result if t["type"] == "pattern" and t.get("priority", 99) < 99]
    assert len(pattern_topics) == 0


# ── trend detection ───────────────────────────────────────────────────────────

def test_mood_decline_trend_detected():
    snaps = [
        _snap(3, valence=0.8),
        _snap(2, valence=0.5),
        _snap(1, valence=0.2),
        _snap(0, valence=-0.1),
    ]
    result = _decide_insights(snaps)
    types = [t["type"] for t in result]
    assert "trend" in types


def test_stable_mood_no_trend():
    snaps = [_snap(i, valence=0.3) for i in range(4)]
    result = _decide_insights(snaps)
    trend_topics = [t for t in result if t["type"] == "trend"]
    assert len(trend_topics) == 0


# ── tag detection ─────────────────────────────────────────────────────────────

def test_frequent_tag_detected():
    snaps = [_snap(i, category="stress", tags=["busy"]) for i in range(5)]
    result = _decide_insights(snaps)
    types = [t["type"] for t in result]
    labels = [t["label"] for t in result]
    assert "tag" in types or any("busy" in l.lower() for l in labels)


def test_tag_needs_four_occurrences():
    snaps = [_snap(i, category="stress", tags=["busy"]) for i in range(3)]
    result = _decide_insights(snaps)
    tag_topics = [t for t in result if t["type"] == "tag"]
    # with only 3 occurrences of "busy", no tag topic should appear
    assert len(tag_topics) == 0


# ── silence gap ───────────────────────────────────────────────────────────────

def test_silence_gap_detected():
    snaps = [_snap(7, category="positive")]  # last entry 7 days ago
    result = _decide_insights(snaps)
    types = [t["type"] for t in result]
    assert "silence" in types


def test_recent_entry_no_silence_gap():
    snaps = [_snap(0, category="positive")]  # entry today
    result = _decide_insights(snaps)
    silence_topics = [t for t in result if t["type"] == "silence" and t.get("evidence", {}).get("days_silent")]
    assert len(silence_topics) == 0


# ── positive peak ─────────────────────────────────────────────────────────────

def test_positive_peak_detected():
    snaps = [_snap(i, category="positive", valence=0.6) for i in range(3)]
    result = _decide_insights(snaps)
    types = [t["type"] for t in result]
    assert "positive" in types


def test_low_valence_no_positive_topic():
    snaps = [_snap(i, category="stress", valence=-0.3) for i in range(3)]
    result = _decide_insights(snaps)
    positive_topics = [t for t in result if t["type"] == "positive"]
    assert len(positive_topics) == 0


# ── deduplication & cap ───────────────────────────────────────────────────────

def test_max_four_topics_returned():
    # Many patterns: 4 stress days, declining valence, frequent busy tag, silence, positive peak
    snaps = [_snap(i, category="stress", valence=max(-0.9 + i * 0.1, -0.9), tags=["busy"]) for i in range(5)]
    result = _decide_insights(snaps)
    assert len(result) <= 4


def test_topics_deduplicated_by_rag_query_prefix():
    # Two identical stress patterns — after dedup only one should survive
    snaps = [_snap(i, category="stress", valence=-0.5, tags=["busy"]) for i in range(6)]
    result = _decide_insights(snaps)
    rag_prefixes = [t["rag_query"].split()[0] if t["rag_query"] else t["label"] for t in result]
    assert len(rag_prefixes) == len(set(rag_prefixes))


def test_all_topics_have_required_fields():
    snaps = [_snap(i, category="positive", valence=0.5) for i in range(3)]
    result = _decide_insights(snaps)
    for t in result:
        assert "label" in t
        assert "rag_query" in t
        assert "type" in t
