"""
Corpus management — incremental export of journal/chat entries to flat files for RAG.
"""

from __future__ import annotations

from pathlib import Path

_corpus_cursor: int = 0  # last exported entry id


def corpus_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "corpus"
    p.mkdir(exist_ok=True)
    return p


def export_corpus_incremental(entries: list[dict]) -> int:
    """
    Write new journal/chat entries to corpus/ as individual text files.
    For voice entries, prefer transcript over empty content; append tone_summary
    as a separate labelled block so RAG can retrieve both what was said and how.
    Returns the new cursor (max id exported), or 0 if nothing new.
    """
    global _corpus_cursor
    if not entries:
        return _corpus_cursor
    corpus = corpus_dir()
    for e in entries:
        fname = corpus / f"{e['id']:08d}.txt"
        date = e["created_at"][:10]
        mode = e["mode"]
        source = e.get("source", "text")

        if source == "voice":
            transcript = (e.get("transcript") or "").strip()
            tone = (e.get("tone_summary") or "").strip()
            if not transcript:
                continue
            body = f"[{date}] [{mode}] [voice]\n{transcript}\n"
            if tone:
                body += f"\n[tone]\n{tone}\n"
        elif source == "image":
            caption = (e.get("image_caption") or "").strip()
            if not caption:
                continue
            body = f"[{date}] [{mode}] [image]\n{caption}\n"
            text_note = (e.get("content") or "").strip()
            if text_note:
                body += f"\n[note]\n{text_note}\n"
        else:
            body = f"[{date}] [{mode}]\n{e['content']}\n"

        fname.write_text(body, encoding="utf-8")

    new_cursor = entries[-1]["id"]
    _corpus_cursor = new_cursor
    return new_cursor
