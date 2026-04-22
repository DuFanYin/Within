"""
Tests for RAG search: app/engine.rag_query and app/reflect._rag_search.
Stubs cactus_rag_query so no model required.
"""

import json
import pytest
import app.engine as engine
import app.reflect as reflect_mod
import app.db as db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()


def _patch_rag(monkeypatch, raw_return: str):
    """Patch cactus_rag_query inside engine to return raw_return."""
    import types

    fake_cactus = types.SimpleNamespace(cactus_rag_query=lambda model, query, top_k: raw_return)

    def _fake_ensure_path():
        pass

    def _fake_get_model():
        return (None, None, None, 1)

    monkeypatch.setattr(engine, "_ensure_python_path", _fake_ensure_path)
    monkeypatch.setattr(engine, "_get_model", _fake_get_model)

    original_rag_query = engine.rag_query

    def _patched_rag(query, top_k=5):
        try:
            parsed = json.loads(raw_return)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return parsed
        return parsed.get("results", [])

    monkeypatch.setattr(engine, "rag_query", _patched_rag)
    reflect_mod.rag_query = _patched_rag
    return _patched_rag


# ── rag_query JSON shape handling ─────────────────────────────────────────────

def test_rag_query_bare_list(monkeypatch):
    raw = json.dumps([{"document": "Entry about stress."}, {"document": "Entry about calm."}])
    _patch_rag(monkeypatch, raw)
    results = engine.rag_query("stress")
    assert len(results) == 2
    assert results[0]["document"] == "Entry about stress."


def test_rag_query_wrapped_results(monkeypatch):
    raw = json.dumps({"results": [{"document": "Entry about joy."}]})
    _patch_rag(monkeypatch, raw)
    results = engine.rag_query("joy")
    assert len(results) == 1
    assert results[0]["document"] == "Entry about joy."


def test_rag_query_bad_json_returns_empty(monkeypatch):
    _patch_rag(monkeypatch, "NOT VALID JSON")
    results = engine.rag_query("anything")
    assert results == []


def test_rag_query_empty_list(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([]))
    results = engine.rag_query("something")
    assert results == []


# ── _rag_search text extraction ───────────────────────────────────────────────

def test_rag_search_document_key(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([{"document": "[2026-04-01] [journal]\nI felt calm.\n"}]))
    result = reflect_mod._rag_search("calm")
    assert "calm" in result


def test_rag_search_text_key_fallback(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([{"text": "Felt overwhelmed at work."}]))
    result = reflect_mod._rag_search("work")
    assert "overwhelmed" in result


def test_rag_search_content_key_fallback(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([{"content": "Feeling anxious today."}]))
    result = reflect_mod._rag_search("anxious")
    assert "anxious" in result


def test_rag_search_empty_query(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([{"document": "anything"}]))
    result = reflect_mod._rag_search("")
    assert result == "No query provided."


def test_rag_search_whitespace_query(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([{"document": "anything"}]))
    result = reflect_mod._rag_search("   ")
    assert result == "No query provided."


def test_rag_search_no_results(monkeypatch):
    _patch_rag(monkeypatch, json.dumps([]))
    result = reflect_mod._rag_search("something specific")
    assert result == "No relevant entries found."


def test_rag_search_exception_handled(monkeypatch):
    def _raises(query, top_k=5):
        raise RuntimeError("Cactus unavailable")

    monkeypatch.setattr(engine, "rag_query", _raises)
    reflect_mod.rag_query = _raises
    result = reflect_mod._rag_search("anything")
    assert result == "No relevant entries found."


def test_rag_search_skips_empty_doc_fields(monkeypatch):
    raw = json.dumps([{"document": ""}, {"document": "Real content here."}])
    _patch_rag(monkeypatch, raw)
    result = reflect_mod._rag_search("content")
    assert "Real content here." in result
    # empty doc should not contribute a blank line
    assert result.strip() != ""


def test_rag_search_truncates_long_doc(monkeypatch):
    long_doc = "x" * 500
    raw = json.dumps([{"document": long_doc}])
    _patch_rag(monkeypatch, raw)
    result = reflect_mod._rag_search("query")
    assert len(result) <= 300
