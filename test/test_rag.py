"""RAG result parsing (Cactus chunk format)."""

import json

import pytest
import app.engine as engine


def test_rag_query_maps_cactus_chunks(monkeypatch):
    raw = json.dumps({"chunks": [{"content": "Felt calm.", "score": 0.9}]})

    monkeypatch.setattr(engine, "_ensure_python_path", lambda: None)
    monkeypatch.setattr(engine, "_get_model", lambda: (None, None, None, 1))
    monkeypatch.setattr(engine, "_cactus_rag_query_fn", lambda m, q, k: raw)

    results = engine.rag_query("calm")
    assert results == [{"document": "Felt calm.", "score": 0.9}]
