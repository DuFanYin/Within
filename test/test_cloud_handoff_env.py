"""CLOUD_HANDOFF master switch (engine.py)."""

import pytest

import app.engine as engine


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setattr(engine, "_load_env_file", lambda: None)
    monkeypatch.delenv("CLOUD_HANDOFF", raising=False)
    monkeypatch.delenv("CACTUS_CLOUD_KEY", raising=False)
    monkeypatch.delenv("CACTUS_CLOUD_API_KEY", raising=False)


def test_disabled_without_flag(monkeypatch):
    monkeypatch.setenv("CACTUS_CLOUD_KEY", "test-key")
    assert engine.cloud_handoff_enabled() is False


def test_enabled_when_true_and_key(monkeypatch):
    monkeypatch.setenv("CLOUD_HANDOFF", "true")
    monkeypatch.setenv("CACTUS_CLOUD_KEY", "test-key")
    assert engine.cloud_handoff_enabled() is True
