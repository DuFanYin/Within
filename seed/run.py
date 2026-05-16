"""
Load manually crafted demo rows into data/journal.db.

Run from repo root:
  python -m seed
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import _conn, init_db  # noqa: E402

from seed.records import RECORDS  # noqa: E402


def _wipe(c) -> int:
    c.execute("DELETE FROM mood_snapshots")
    cur = c.execute("DELETE FROM journal_entries")
    return cur.rowcount or 0


def seed() -> None:
    init_db()
    with _conn() as c:
        removed = _wipe(c)
        if removed:
            print(f"Wiped {removed} journal_entries (and mood_snapshots).")

        now = datetime.now(timezone.utc)
        inserted = 0
        mood_count = 0

        for row in RECORDS:
            (
                days_ago,
                hour,
                mode,
                role,
                content,
                source,
                session,
                valence,
                intensity,
                category,
                sub_tags,
            ) = row
            ts = (now - timedelta(days=days_ago)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            cur = c.execute(
                "INSERT INTO journal_entries(created_at, mode, role, content, source, session_id) "
                "VALUES (?,?,?,?,?,?)",
                (ts_str, mode, role, content, source, session),
            )
            entry_id = cur.lastrowid

            if role == "user" and valence is not None:
                c.execute(
                    "INSERT INTO mood_snapshots(entry_id, created_at, valence, intensity, category, sub_tags) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        entry_id,
                        ts_str,
                        valence,
                        intensity,
                        category,
                        json.dumps(sub_tags, ensure_ascii=False),
                    ),
                )
                mood_count += 1
            inserted += 1

        span = max(r[0] for r in RECORDS)
        print(
            f"Seeded {inserted} entries across ~{span} days "
            f"({mood_count} user rows with mood tags)."
        )


if __name__ == "__main__":
    seed()
