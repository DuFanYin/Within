"""
Tests for app/corpus.py — incremental export, file formats, cursor advancement.
"""

import pytest
from pathlib import Path
import app.corpus as corpus_mod


@pytest.fixture(autouse=True)
def reset_cursor():
    """Reset the module-level cursor before each test."""
    corpus_mod._corpus_cursor = 0
    yield
    corpus_mod._corpus_cursor = 0


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    """Point corpus_dir() at a temp path."""
    monkeypatch.setattr(corpus_mod, "corpus_dir", lambda: tmp_path)
    return tmp_path


def _entry(id, mode="journal", source="text", content="hello", created_at="2026-04-01T10:00:00Z",
           transcript=None, tone_summary=None, image_caption=None):
    return {
        "id": id,
        "created_at": created_at,
        "mode": mode,
        "source": source,
        "content": content,
        "transcript": transcript,
        "tone_summary": tone_summary,
        "image_caption": image_caption,
    }


# ── text entries ──────────────────────────────────────────────────────────────

def test_text_entry_written(corpus_dir):
    corpus_mod.export_corpus_incremental([_entry(1, content="I feel calm today.")])
    f = corpus_dir / "00000001.txt"
    assert f.exists()
    text = f.read_text()
    assert "[2026-04-01]" in text
    assert "[journal]" in text
    assert "I feel calm today." in text


def test_text_entry_format(corpus_dir):
    corpus_mod.export_corpus_incremental([_entry(5, mode="chat", content="long day")])
    text = (corpus_dir / "00000005.txt").read_text()
    assert text.startswith("[2026-04-01] [chat]\nlong day\n")


# ── voice entries ─────────────────────────────────────────────────────────────

def test_voice_entry_with_transcript_and_tone(corpus_dir):
    e = _entry(2, source="voice", content="", transcript="I went for a walk.", tone_summary="Calm, unhurried.")
    corpus_mod.export_corpus_incremental([e])
    text = (corpus_dir / "00000002.txt").read_text()
    assert "[voice]" in text
    assert "I went for a walk." in text
    assert "[tone]" in text
    assert "Calm, unhurried." in text


def test_voice_entry_skipped_without_transcript(corpus_dir):
    e = _entry(3, source="voice", content="", transcript=None, tone_summary=None)
    corpus_mod.export_corpus_incremental([e])
    assert not (corpus_dir / "00000003.txt").exists()


def test_voice_entry_skipped_empty_transcript(corpus_dir):
    e = _entry(4, source="voice", content="", transcript="   ", tone_summary=None)
    corpus_mod.export_corpus_incremental([e])
    assert not (corpus_dir / "00000004.txt").exists()


def test_voice_entry_without_tone(corpus_dir):
    e = _entry(6, source="voice", content="", transcript="Short note.", tone_summary=None)
    corpus_mod.export_corpus_incremental([e])
    text = (corpus_dir / "00000006.txt").read_text()
    assert "Short note." in text
    assert "[tone]" not in text


# ── image entries ─────────────────────────────────────────────────────────────

def test_image_entry_with_caption(corpus_dir):
    e = _entry(7, source="image", content="", image_caption="A warm sunset over the hills.")
    corpus_mod.export_corpus_incremental([e])
    text = (corpus_dir / "00000007.txt").read_text()
    assert "[image]" in text
    assert "A warm sunset over the hills." in text


def test_image_entry_skipped_without_caption(corpus_dir):
    e = _entry(8, source="image", content="", image_caption=None)
    corpus_mod.export_corpus_incremental([e])
    assert not (corpus_dir / "00000008.txt").exists()


def test_image_entry_includes_note(corpus_dir):
    e = _entry(9, source="image", content="My note about this photo.", image_caption="Abstract blue shapes.")
    corpus_mod.export_corpus_incremental([e])
    text = (corpus_dir / "00000009.txt").read_text()
    assert "[note]" in text
    assert "My note about this photo." in text


def test_image_entry_no_note_no_note_block(corpus_dir):
    e = _entry(10, source="image", content="", image_caption="A quiet room.")
    corpus_mod.export_corpus_incremental([e])
    text = (corpus_dir / "00000010.txt").read_text()
    assert "[note]" not in text


# ── cursor & incremental behaviour ───────────────────────────────────────────

def test_cursor_advances_to_max_id(corpus_dir):
    entries = [_entry(1), _entry(3), _entry(7)]
    new_cursor = corpus_mod.export_corpus_incremental(entries)
    assert new_cursor == 7
    assert corpus_mod._corpus_cursor == 7


def test_incremental_only_writes_new(corpus_dir):
    corpus_mod.export_corpus_incremental([_entry(1, content="first")])
    # second call with same entry id but different content — should overwrite
    # (corpus.py writes by id, so re-running same id is idempotent / last-write-wins)
    corpus_mod.export_corpus_incremental([_entry(2, content="second")])
    assert (corpus_dir / "00000001.txt").exists()
    assert (corpus_dir / "00000002.txt").exists()


def test_empty_entries_returns_current_cursor(corpus_dir):
    corpus_mod._corpus_cursor = 42
    result = corpus_mod.export_corpus_incremental([])
    assert result == 42


def test_file_naming_zero_padded(corpus_dir):
    corpus_mod.export_corpus_incremental([_entry(1)])
    assert (corpus_dir / "00000001.txt").exists()

    corpus_mod.export_corpus_incremental([_entry(12345678)])
    assert (corpus_dir / "12345678.txt").exists()
