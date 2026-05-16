"""Rule-based cloud handoff routing."""

from app.handoff_intent import route_mode


def test_crisis_stays_local():
    assert route_mode("I want to hurt myself", cloud_configured=True) == "crisis"


def test_skills_routes_to_cloud_when_configured():
    assert route_mode("How can I cope with stress at work?", cloud_configured=True) == "skills_cloud"


def test_reflective_stays_local():
    assert route_mode("Why have I felt so drained lately?", cloud_configured=True) == "local"


def test_no_cloud_without_key():
    assert route_mode("How can I cope with this?", cloud_configured=False) == "local"
