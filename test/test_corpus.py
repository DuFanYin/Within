"""Corpus export formats for text, transcribed voice, and captioned images."""

import pytest
from pathlib import Path
import app.corpus as corpus_mod


@pytest.fixture(autouse=True)
def reset_cursor():
    corpus_mod._corpus_cursor = 0
    yield
    corpus_mod._corpus_cursor = 0


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_mod, "corpus_dir", lambda: tmp_path)
    return tmp_path


def _entry(entry_id, **kwargs):
    base = {
        "id": entry_id,
        "created_at": "2026-04-01T10:00:00Z",
        "mode": "journal",
        "source": "text",
        "content": "hello",
        "transcript": None,
        "tone_summary": None,
        "image_caption": None,
    }
    base.update(kwargs)
    return base


def test_export_text_journal(corpus_dir):
    corpus_mod.export_corpus_incremental([_entry(1, content="I feel calm today.")])
    text = (corpus_dir / "00000001.txt").read_text()
    assert "[journal]" in text and "I feel calm today." in text


def test_export_voice_waits_for_transcript(corpus_dir):
    pending = _entry(2, source="voice", content="", transcript=None)
    corpus_mod.export_corpus_incremental([pending])
    assert not (corpus_dir / "00000002.txt").exists()

    done = _entry(2, source="voice", content="", transcript="I went for a walk.", tone_summary="Calm.")
    corpus_mod.export_corpus_incremental([done])
    text = (corpus_dir / "00000002.txt").read_text()
    assert "I went for a walk." in text and "[tone]" in text


def test_export_image_waits_for_caption(corpus_dir):
    pending = _entry(3, source="image", content="", image_caption=None)
    corpus_mod.export_corpus_incremental([pending])
    assert not (corpus_dir / "00000003.txt").exists()

    done = _entry(
        3, source="image", content="My note.", image_caption="Sunset over hills."
    )
    corpus_mod.export_corpus_incremental([done])
    text = (corpus_dir / "00000003.txt").read_text()
    assert "Sunset over hills." in text and "My note." in text
