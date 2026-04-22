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
        # Migrations for existing databases
        existing = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "journal_entries" in existing:
            cols = {row[1] for row in c.execute("PRAGMA table_info(journal_entries)")}
            if "audio_id" not in cols:
                c.execute("ALTER TABLE journal_entries ADD COLUMN audio_id INTEGER REFERENCES audio_files(id)")
            if "image_id" not in cols:
                c.execute("ALTER TABLE journal_entries ADD COLUMN image_id INTEGER REFERENCES image_files(id)")
            if "source" not in cols:
                c.execute("ALTER TABLE journal_entries ADD COLUMN source TEXT NOT NULL DEFAULT 'text'")
            # Widen mode CHECK to include 'reflect' — recreate table if old constraint is too narrow
            create_sql = c.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='journal_entries'"
            ).fetchone()
            if create_sql and "'reflect'" not in create_sql[0]:
                c.executescript("""
                    ALTER TABLE journal_entries RENAME TO _journal_entries_old;
                    CREATE TABLE journal_entries (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                        mode        TEXT    NOT NULL CHECK(mode IN ('chat','journal','reflect')),
                        role        TEXT    NOT NULL CHECK(role IN ('user','assistant','summary')),
                        content     TEXT    NOT NULL,
                        source      TEXT    NOT NULL DEFAULT 'text' CHECK(source IN ('text','voice','image')),
                        session_id  TEXT,
                        audio_id    INTEGER REFERENCES audio_files(id),
                        image_id    INTEGER REFERENCES image_files(id)
                    );
                    INSERT INTO journal_entries
                        SELECT id, created_at,
                               CASE WHEN mode NOT IN ('chat','journal','reflect') THEN 'chat' ELSE mode END,
                               role, content, source, session_id, audio_id, image_id
                        FROM _journal_entries_old;
                    DROP TABLE _journal_entries_old;
                    CREATE INDEX IF NOT EXISTS idx_entries_created ON journal_entries(created_at);
                    CREATE INDEX IF NOT EXISTS idx_entries_session  ON journal_entries(session_id);
                    CREATE INDEX IF NOT EXISTS idx_entries_audio    ON journal_entries(audio_id);
                    CREATE INDEX IF NOT EXISTS idx_entries_image    ON journal_entries(image_id);
                """)
        c.commit()

        c.executescript("""
            CREATE TABLE IF NOT EXISTS audio_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                filename    TEXT    NOT NULL,
                duration_s  REAL,
                size_bytes  INTEGER,
                transcript  TEXT,
                tone_summary TEXT
            );

            CREATE TABLE IF NOT EXISTS image_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                filename    TEXT    NOT NULL,
                mime_type   TEXT    NOT NULL DEFAULT 'image/jpeg',
                size_bytes  INTEGER,
                caption     TEXT
            );

            CREATE TABLE IF NOT EXISTS journal_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                mode        TEXT    NOT NULL CHECK(mode IN ('chat','journal','reflect')),
                role        TEXT    NOT NULL CHECK(role IN ('user','assistant','summary')),
                content     TEXT    NOT NULL,
                source      TEXT    NOT NULL DEFAULT 'text' CHECK(source IN ('text','voice','image')),
                session_id  TEXT,
                audio_id    INTEGER REFERENCES audio_files(id),
                image_id    INTEGER REFERENCES image_files(id)
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
            CREATE INDEX IF NOT EXISTS idx_entries_audio  ON journal_entries(audio_id);
            CREATE INDEX IF NOT EXISTS idx_entries_image  ON journal_entries(image_id);
        """)


# ── writes ────────────────────────────────────────────────────────────────────

def save_image_file(filename: str, mime_type: str, size_bytes: int) -> int:
    """Save an image file record; returns the new image_files.id."""
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO image_files(filename, mime_type, size_bytes) VALUES (?,?,?)",
            (filename, mime_type, size_bytes),
        )
        return cur.lastrowid  # type: ignore[return-value]


def update_image_caption(image_id: int, caption: str) -> None:
    """Write back the AI-generated caption for an image."""
    with _conn() as c:
        c.execute("UPDATE image_files SET caption=? WHERE id=?", (caption, image_id))


def get_pending_image_entries() -> list[dict[str, Any]]:
    """Return journal_entries with an image_id but no caption yet."""
    with _conn() as c:
        rows = c.execute("""
            SELECT e.id as entry_id, i.id as image_id, i.filename, i.mime_type
            FROM journal_entries e
            JOIN image_files i ON i.id = e.image_id
            WHERE i.caption IS NULL
            ORDER BY e.id
        """).fetchall()
    return [dict(r) for r in rows]


def save_audio_file(filename: str, size_bytes: int, duration_s: float | None = None) -> int:
    """Save a stored audio file record; returns the new audio_files.id."""
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO audio_files(filename, size_bytes, duration_s) VALUES (?,?,?)",
            (filename, size_bytes, duration_s),
        )
        return cur.lastrowid  # type: ignore[return-value]


def update_audio_transcript(audio_id: int, transcript: str, tone_summary: str) -> None:
    """Write back ASR transcript and tone summary generated by background job."""
    with _conn() as c:
        c.execute(
            "UPDATE audio_files SET transcript=?, tone_summary=? WHERE id=?",
            (transcript, tone_summary, audio_id),
        )


def update_entry_content(entry_id: int, content: str) -> None:
    """Backfill content on an entry (e.g. after ASR completes for a voice entry)."""
    with _conn() as c:
        c.execute("UPDATE journal_entries SET content=? WHERE id=?", (content, entry_id))



def save_entry(
    mode: str,
    role: str,
    content: str,
    source: str = "text",
    session_id: str | None = None,
    audio_id: int | None = None,
    image_id: int | None = None,
) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO journal_entries(mode, role, content, source, session_id, audio_id, image_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (mode, role, content, source, session_id, audio_id, image_id),
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

def get_recent_mood(days: int = 14) -> list[dict[str, Any]]:
    """
    Return one row per mood_snapshot in the last N days, newest first.
    Each row: { day, valence, intensity, category, sub_tags (list) }
    Used by the insight agent decision layer.
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT substr(m.created_at,1,10) as day,
                   m.valence, m.intensity, m.category, m.sub_tags
            FROM mood_snapshots m
            WHERE m.created_at >= datetime('now', ? || ' days')
            ORDER BY m.created_at DESC
        """, (f"-{days}",)).fetchall()
    out = []
    for r in rows:
        try:
            tags = json.loads(r["sub_tags"]) if r["sub_tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        out.append({
            "day": r["day"],
            "valence": r["valence"],
            "intensity": r["intensity"],
            "category": r["category"],
            "sub_tags": tags,
        })
    return out


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


def get_pending_audio_entries() -> list[dict[str, Any]]:
    """
    Return journal_entries that have an audio_id but whose audio_files record
    has no transcript yet (background ASR not yet run).
    Returns [{entry_id, audio_id, filename}].
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT e.id as entry_id, a.id as audio_id, a.filename
            FROM journal_entries e
            JOIN audio_files a ON a.id = e.audio_id
            WHERE a.transcript IS NULL
            ORDER BY e.id
        """).fetchall()
    return [dict(r) for r in rows]


def get_corpus_entries(since_id: int = 0) -> list[dict[str, Any]]:
    """
    Return all user journal/chat entries with id > since_id for corpus export.
    For voice entries, include transcript and tone_summary from audio_files.
    Returns list of {id, created_at, mode, content, source, transcript, tone_summary}.
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT e.id, e.created_at, e.mode, e.content, e.source,
                   a.transcript, a.tone_summary,
                   i.caption as image_caption
            FROM journal_entries e
            LEFT JOIN audio_files a ON a.id = e.audio_id
            LEFT JOIN image_files i ON i.id = e.image_id
            WHERE e.role = 'user' AND e.id > ?
            ORDER BY e.id
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
    view='calendar': per-day total count plus category breakdown for the calendar mosaic.
    day='YYYY-MM-DD': entries for that day only.
    """
    with _conn() as c:
        if view == "calendar":
            rows = c.execute("""
                SELECT substr(e.created_at, 1, 10) AS day,
                       COALESCE(NULLIF(TRIM(m.category), ''), '_none') AS category,
                       COUNT(*) AS cnt
                FROM journal_entries e
                LEFT JOIN mood_snapshots m ON m.entry_id = e.id
                WHERE e.role = 'user'
                GROUP BY day, category
                ORDER BY day ASC
            """).fetchall()
            by_day: dict[str, dict[str, Any]] = {}
            for r in rows:
                day = r["day"]
                cat = r["category"]
                cnt = int(r["cnt"])
                if day not in by_day:
                    by_day[day] = {"day": day, "count": 0, "categories": {}}
                by_day[day]["categories"][cat] = cnt
                by_day[day]["count"] += cnt
            return sorted(by_day.values(), key=lambda x: x["day"], reverse=True)

        query = """
            SELECT e.id, e.created_at, e.mode, e.content, e.source, e.audio_id, e.image_id,
                   m.valence, m.intensity, m.category, m.sub_tags,
                   a.tone_summary,
                   i.filename as image_filename, i.caption as image_caption
            FROM journal_entries e
            LEFT JOIN mood_snapshots m ON m.entry_id = e.id
            LEFT JOIN audio_files a ON a.id = e.audio_id
            LEFT JOIN image_files i ON i.id = e.image_id
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
                "audio_id": r["audio_id"],
                "tone_summary": r["tone_summary"],
                "image_id": r["image_id"],
                "image_filename": r["image_filename"],
                "image_caption": r["image_caption"],
                "valence": r["valence"],
                "intensity": r["intensity"],
                "category": r["category"],
                "sub_tags": json.loads(r["sub_tags"]) if r["sub_tags"] else [],
            })
        return out


# ── agent tool backends ───────────────────────────────────────────────────────

def get_mood_stats_for_agent(days: int = 14) -> dict[str, Any]:
    """
    Return a compact mood summary for the last N days.
    Used as the backing function for the LLM get_mood_stats tool.
    { category_counts, top_tags, avg_valence, total_entries }
    """
    with _conn() as c:
        cat_rows = c.execute("""
            SELECT category, COUNT(*) as count
            FROM mood_snapshots
            WHERE category IS NOT NULL
              AND created_at >= datetime('now', ? || ' days')
            GROUP BY category ORDER BY count DESC
        """, (f"-{days}",)).fetchall()

        val_row = c.execute("""
            SELECT AVG(valence) as avg_v, COUNT(*) as total
            FROM mood_snapshots
            WHERE valence IS NOT NULL
              AND created_at >= datetime('now', ? || ' days')
        """, (f"-{days}",)).fetchone()

        tag_rows = c.execute("""
            SELECT sub_tags FROM mood_snapshots
            WHERE sub_tags IS NOT NULL AND sub_tags != '[]'
              AND created_at >= datetime('now', ? || ' days')
        """, (f"-{days}",)).fetchall()

    tag_counts: dict[str, int] = {}
    for r in tag_rows:
        try:
            for t in json.loads(r["sub_tags"]):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "category_counts": {r["category"]: r["count"] for r in cat_rows},
        "top_tags": [{"tag": t, "count": n} for t, n in top_tags],
        "avg_valence": round(val_row["avg_v"], 3) if val_row["avg_v"] is not None else None,
        "total_entries": val_row["total"] or 0,
        "days": days,
    }


def get_last_reflect_summary() -> dict[str, Any] | None:
    """
    Return the most recent reflect session summary: the last user message sent
    during a reflect chat, plus its date. Used to give the greeting a sense of
    continuity ("Last time you mentioned…").
    Returns None if no reflect session found within the last 30 days.
    """
    with _conn() as c:
        row = c.execute("""
            SELECT content, created_at
            FROM journal_entries
            WHERE role = 'user'
              AND mode = 'reflect'
              AND content IS NOT NULL AND content != ''
              AND created_at >= datetime('now', '-30 days')
            ORDER BY created_at DESC
            LIMIT 1
        """).fetchone()
    if not row:
        return None
    return {"content": row["content"], "created_at": row["created_at"][:10]}


