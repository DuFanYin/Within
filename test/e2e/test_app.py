"""
End-to-end with real on-device model (skipped if Cactus not built).
"""

import time

import app.corpus as corpus_mod
import app.db as db_mod

from support import collect_sse, log_step


async def test_companion_chat(client):
    log_step("companion chat …")
    t0 = time.monotonic()
    r = await client.post("/api/companion/chat", json={"message": "Hi"})
    log_step(f"companion done ({time.monotonic() - t0:.1f}s)")
    assert r.status_code == 200
    done = [e for e in collect_sse(r.text) if e.get("done")][0]
    assert done.get("reply")
    assert len(db_mod.get_session_messages(done["session_id"])) >= 2


async def test_reflect_open(client):
    eid = db_mod.save_entry("journal", "user", "Overwhelmed and tired from work.")
    db_mod.save_mood(eid, -0.5, 0.7, "stress", ["work"], "{}")

    log_step("reflect open …")
    t0 = time.monotonic()
    r = await client.get("/api/reflect/open")
    log_step(f"reflect done ({time.monotonic() - t0:.1f}s)")
    assert r.status_code == 200
    result = [e for e in collect_sse(r.text) if "result" in e][0]["result"]
    assert result["greeting"]
    assert any(t["type"] == "just_chat" for t in result["topics"])


async def test_journal_and_corpus_sync(client):
    text = "E2E journal phrase for corpus."
    await client.post("/api/journal", json={"text": text})
    assert (await client.post("/api/dev/sync-corpus")).json()["ok"] is True
    assert any(text in f.read_text() for f in corpus_mod.corpus_dir().glob("*.txt"))
