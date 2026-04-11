"""
SQLite persistence layer.
DB file: {app_root}/data/journal.db
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

_DB_PATH: Path | None = None


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        root = Path(__file__).resolve().parent.parent
        data = root / "data"
        data.mkdir(exist_ok=True)
        _DB_PATH = data / "journal.db"
    return _DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                mode        TEXT    NOT NULL CHECK(mode IN ('chat','journal')),
                role        TEXT    NOT NULL CHECK(role IN ('user','assistant','summary')),
                content     TEXT    NOT NULL,
                source      TEXT    NOT NULL DEFAULT 'text' CHECK(source IN ('text','voice')),
                session_id  TEXT
            );

            CREATE TABLE IF NOT EXISTS mood_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id        INTEGER NOT NULL REFERENCES journal_entries(id),
                created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                valence         REAL,
                intensity       REAL,
                category        TEXT,
                sub_tags        TEXT    NOT NULL DEFAULT '[]',
                raw_json        TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_entries_created ON journal_entries(created_at);
            CREATE INDEX IF NOT EXISTS idx_entries_session ON journal_entries(session_id);
            CREATE INDEX IF NOT EXISTS idx_mood_entry     ON mood_snapshots(entry_id);
        """)


# ── writes ────────────────────────────────────────────────────────────────────

def save_entry(
    mode: str,
    role: str,
    content: str,
    source: str = "text",
    session_id: str | None = None,
) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO journal_entries(mode, role, content, source, session_id) VALUES (?,?,?,?,?)",
            (mode, role, content, source, session_id),
        )
        return cur.lastrowid  # type: ignore[return-value]


def save_mood(
    entry_id: int,
    valence: float | None,
    intensity: float | None,
    category: str | None,
    sub_tags: list[str],
    raw: str,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO mood_snapshots(entry_id, valence, intensity, category, sub_tags, raw_json) VALUES (?,?,?,?,?,?)",
            (entry_id, valence, intensity, category, json.dumps(sub_tags), raw),
        )


# ── reads ─────────────────────────────────────────────────────────────────────

def get_session_messages(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return last N chat messages for a session as {role, content} dicts."""
    with _conn() as c:
        rows = c.execute(
            """SELECT role, content FROM journal_entries
               WHERE session_id = ? AND mode = 'chat'
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_stats() -> dict[str, Any]:
    """
    Returns:
      - daily: [{day, valence, intensity, count}] newest-first (up to 90 days)
      - tags: [{tag, count}] top 20 most frequent emotion tags
    """
    with _conn() as c:
        daily_rows = c.execute("""
            SELECT substr(m.created_at,1,10) as day,
                   AVG(m.valence)   as valence,
                   AVG(m.intensity) as intensity,
                   COUNT(*)         as count
            FROM mood_snapshots m
            WHERE m.valence IS NOT NULL
            GROUP BY day
            ORDER BY day DESC
            LIMIT 90
        """).fetchall()

        sub_tag_rows = c.execute("""
            SELECT sub_tags FROM mood_snapshots WHERE sub_tags IS NOT NULL AND sub_tags != '[]'
        """).fetchall()

        category_rows = c.execute("""
            SELECT category, COUNT(*) as count
            FROM mood_snapshots WHERE category IS NOT NULL
            GROUP BY category ORDER BY count DESC
        """).fetchall()

    # flatten and count sub_tags
    tag_counts: dict[str, int] = {}
    for r in sub_tag_rows:
        try:
            for t in json.loads(r["sub_tags"]):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "daily": [
            {
                "day": r["day"],
                "valence": round(r["valence"], 3),
                "intensity": round(r["intensity"], 3),
                "count": r["count"],
            }
            for r in daily_rows
        ],
        "tags": [{"tag": t, "count": n} for t, n in top_tags],
        "categories": [{"category": r["category"], "count": r["count"]} for r in category_rows],
    }


def get_corpus_entries(since_id: int = 0) -> list[dict[str, Any]]:
    """
    Return all user journal/chat entries with id > since_id for corpus export.
    Returns list of {id, created_at, mode, content}.
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT id, created_at, mode, content
            FROM journal_entries
            WHERE role = 'user' AND id > ?
            ORDER BY id
        """, (since_id,)).fetchall()
    return [dict(r) for r in rows]


def get_days_needing_summary() -> list[str]:
    """
    Return dates (YYYY-MM-DD) that have user chat messages but no summary yet,
    and are strictly before today.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute("""
            SELECT DISTINCT substr(created_at,1,10) as day
            FROM journal_entries
            WHERE mode='chat' AND role='user'
              AND substr(created_at,1,10) < ?
              AND substr(created_at,1,10) NOT IN (
                  SELECT substr(created_at,1,10) FROM journal_entries
                  WHERE mode='chat' AND role='summary'
              )
            ORDER BY day
        """, (today,)).fetchall()
    return [r["day"] for r in rows]


def get_day_chat_messages(day: str) -> list[str]:
    """Return all user chat messages for a given day (YYYY-MM-DD), oldest first."""
    with _conn() as c:
        rows = c.execute("""
            SELECT content FROM journal_entries
            WHERE mode='chat' AND role='user'
              AND substr(created_at,1,10) = ?
            ORDER BY id
        """, (day,)).fetchall()
    return [r["content"] for r in rows]


def save_summary(day: str, summary_text: str) -> int:
    """Save a daily summary as a special entry timestamped at end-of-day."""
    timestamp = f"{day}T23:59:59Z"
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO journal_entries(created_at, mode, role, content, source) VALUES (?,?,?,?,?)",
            (timestamp, "chat", "summary", summary_text, "text"),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_history(view: str = "timeline", day: str | None = None) -> list[dict[str, Any]]:
    """
    view='timeline': all user entries newest-first, with mood tags.
    view='calendar': group counts by date.
    day='YYYY-MM-DD': entries for that day only.
    """
    with _conn() as c:
        if view == "calendar":
            rows = c.execute("""
                SELECT substr(created_at,1,10) as day, COUNT(*) as count
                FROM journal_entries WHERE role='user'
                GROUP BY day ORDER BY day DESC
            """).fetchall()
            return [dict(r) for r in rows]

        query = """
            SELECT e.id, e.created_at, e.mode, e.content, e.source,
                   m.valence, m.intensity, m.category, m.sub_tags
            FROM journal_entries e
            LEFT JOIN mood_snapshots m ON m.entry_id = e.id
            WHERE e.role = 'user'
        """
        params: list[Any] = []
        if day:
            query += " AND substr(e.created_at,1,10) = ?"
            params.append(day)
        query += " ORDER BY e.id DESC LIMIT 200"

        rows = c.execute(query, params).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "created_at": r["created_at"],
                "mode": r["mode"],
                "content": r["content"],
                "source": r["source"],
                "valence": r["valence"],
                "intensity": r["intensity"],
                "category": r["category"],
                "sub_tags": json.loads(r["sub_tags"]) if r["sub_tags"] else [],
            })
        return out


