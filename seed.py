"""
Fake history seeder — one month of data, some days skipped, some days busy.

Run from the app root:
  python seed.py

**Wipes** mood_snapshots and journal_entries, then inserts seed rows (safe to re-run).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from app.db import init_db, _conn  # noqa: E402


def _wipe(c) -> int:
    c.execute("DELETE FROM mood_snapshots")
    cur = c.execute("DELETE FROM journal_entries")
    return cur.rowcount or 0


# (days_ago, mode, role, content, source, session_id, valence, intensity, category, sub_tags)
_SEED = [
    # ── Day 30 — anxious week start ───────────────────────────────────────────
    (30, "journal", "user",
     "First day back after the holiday. Inbox was a disaster. Couldn't focus for more than ten minutes at a time. Why do vacations always make re-entry harder?",
     "text", None, -0.5, 0.65, "anxiety", ["worried", "uneasy"]),

    (30, "chat", "user",
     "I always feel like I'm behind. Like everyone else just naturally keeps up and I'm always catching up.",
     "text", "s1", -0.45, 0.6, "anxiety", ["out_of_control", "future_anxiety"]),
    (30, "chat", "assistant",
     "That feeling of constantly catching up is exhausting. Do you think it's really true, or is it the story your brain tells you when you're overwhelmed?",
     "text", "s1", None, None, None, []),

    # ── Day 28 — busy, stressed ───────────────────────────────────────────────
    (28, "journal", "user",
     "Three meetings before lunch. By noon I was already running on empty. Skipped the gym. Ate at my desk. Classic.",
     "text", None, -0.4, 0.7, "stress", ["exhausted", "drained"]),

    (28, "chat", "user",
     "I said yes to too many things again this week and now I'm drowning.",
     "text", "s2", -0.5, 0.75, "stress", ["overwhelmed", "time_crunched"]),
    (28, "chat", "assistant",
     "Drowning in commitments you chose — there's a particular guilt that comes with that. What's the one thing you could drop this week without real consequences?",
     "text", "s2", None, None, None, []),
    (28, "chat", "user",
     "Probably the Friday sync. No one actually needs it.",
     "text", "s2", 0.1, 0.4, "stress", ["busy"]),

    # ── Day 27 — heavy, low mood ──────────────────────────────────────────────
    (27, "journal", "user",
     "Didn't want to get out of bed. Just lay there listening to the rain. Eventually did, but it felt like moving through water all day.",
     "text", None, -0.65, 0.6, "low_mood", ["helpless", "unmotivated"]),

    (27, "journal", "user",
     "Tried to journal in the morning but nothing came out. Just stared at the page. Sometimes silence is the only honest thing.",
     "voice", None, -0.55, 0.5, "low_mood", ["empty", "lost"]),

    # ── Day 25 — skipped ─────────────────────────────────────────────────────
    # ── Day 24 — skipped ─────────────────────────────────────────────────────

    # ── Day 23 — social tension ───────────────────────────────────────────────
    (23, "chat", "user",
     "Had dinner with old friends. Everyone seemed to have it together — promotions, relationships, apartments they actually own. I smiled through the whole thing.",
     "text", "s3", -0.55, 0.7, "social", ["jealous", "comparison_anxiety"]),
    (23, "chat", "assistant",
     "Performing okay when you don't feel it takes a toll. What was the moment during dinner you felt most distant from the conversation?",
     "text", "s3", None, None, None, []),
    (23, "chat", "user",
     "When they started talking about buying property. I just… checked out internally.",
     "text", "s3", -0.4, 0.55, "social", ["lonely", "overlooked"]),

    (23, "journal", "user",
     "Came home and sat in the dark for a bit. Not sad exactly. Just needed to decompress from all the performing.",
     "text", None, -0.3, 0.45, "low_mood", ["empty"]),

    # ── Day 21 — slightly better ──────────────────────────────────────────────
    (21, "journal", "user",
     "Woke up before the alarm. Made proper breakfast. Small wins.",
     "text", None, 0.3, 0.35, "positive", ["content"]),

    # ── Day 20 — skipped ─────────────────────────────────────────────────────

    # ── Day 19 — good day ─────────────────────────────────────────────────────
    (19, "chat", "user",
     "I finally finished the project I've been dragging for a month. Submitted it this afternoon. I feel… lighter.",
     "text", "s4", 0.75, 0.65, "positive", ["accomplished", "relaxed"]),
    (19, "chat", "assistant",
     "That lightness is real — you earned it. What made you able to push through today?",
     "text", "s4", None, None, None, []),
    (19, "chat", "user",
     "I just started. Stopped waiting to be in the mood.",
     "text", "s4", 0.6, 0.5, "positive", ["accomplished"]),

    (19, "journal", "user",
     "Went for a run after submitting. The city felt different — like I had space in my chest again.",
     "text", None, 0.7, 0.55, "positive", ["happy", "relaxed"]),

    # ── Day 17 — anger, frustration ───────────────────────────────────────────
    (17, "journal", "user",
     "My manager publicly credited someone else for my work in the all-hands. I didn't say anything. I should have.",
     "text", None, -0.7, 0.8, "anger", ["unfair", "offended"]),

    (17, "chat", "user",
     "I'm furious but I keep it so contained that no one even knows. Is that healthy?",
     "voice", "s5", -0.65, 0.75, "anger", ["suppressed_anger", "irritable"]),
    (17, "chat", "assistant",
     "Contained anger isn't the same as resolved anger. It tends to leak. Is there a safe place you could let some of it out — even just on paper?",
     "text", "s5", None, None, None, []),

    # ── Day 15 — skipped ─────────────────────────────────────────────────────
    # ── Day 14 — skipped ─────────────────────────────────────────────────────

    # ── Day 13 — quiet recovery ───────────────────────────────────────────────
    (13, "journal", "user",
     "Quiet Saturday. Made coffee, read for two hours, didn't check my phone until noon. I'd forgotten what that felt like.",
     "text", None, 0.5, 0.4, "positive", ["relaxed", "content"]),

    # ── Day 12 — anxious again ────────────────────────────────────────────────
    (12, "chat", "user",
     "Performance review next week. I've been dreading it for a month. What if they've been disappointed in me this whole time and just never said?",
     "text", "s6", -0.6, 0.8, "anxiety", ["worried", "future_anxiety"]),
    (12, "chat", "assistant",
     "That anticipatory dread is often worse than the thing itself. What's the most realistic outcome you can imagine — not worst-case, not best?",
     "text", "s6", None, None, None, []),
    (12, "chat", "user",
     "Probably fine. My manager seemed okay last week. I just spiral.",
     "text", "s6", -0.1, 0.5, "anxiety", ["uneasy"]),

    (12, "journal", "user",
     "Can't stop rehearsing the review conversation in my head. Different versions. All of them bad.",
     "voice", None, -0.5, 0.7, "anxiety", ["out_of_control", "worried"]),

    # ── Day 10 — good feedback ────────────────────────────────────────────────
    (10, "chat", "user",
     "Review went well. Better than I expected. My manager said I've been 'quietly indispensable.' I didn't know what to do with that.",
     "text", "s7", 0.7, 0.6, "positive", ["accomplished", "content"]),
    (10, "chat", "assistant",
     "Quietly indispensable — that's a real compliment. How did it land for you in the moment?",
     "text", "s7", None, None, None, []),
    (10, "chat", "user",
     "I said thank you and then immediately worried it was a backhanded way of saying I'm not visible enough.",
     "text", "s7", 0.2, 0.45, "anxiety", ["uneasy"]),

    # ── Day 8 — social warmth ─────────────────────────────────────────────────
    (8, "journal", "user",
     "Called my sister for no reason. Just talked for an hour about nothing. I needed that more than I realized.",
     "text", None, 0.65, 0.55, "positive", ["happy", "content"]),

    # ── Day 6 — skipped ──────────────────────────────────────────────────────

    # ── Day 5 — heavy week end ────────────────────────────────────────────────
    (5, "chat", "user",
     "I feel like I'm always managing other people's emotions and nobody manages mine.",
     "text", "s8", -0.55, 0.7, "social", ["lonely", "overlooked"]),
    (5, "chat", "assistant",
     "Being the one who holds space for everyone else is quietly depleting. When did you last let someone hold space for you?",
     "text", "s8", None, None, None, []),
    (5, "chat", "user",
     "I don't know. Maybe never. I don't think I know how to let that happen.",
     "text", "s8", -0.4, 0.6, "social", ["lonely"]),

    (5, "journal", "user",
     "Long week. Didn't exercise once. Ate badly. Slept badly. The whole package.",
     "text", None, -0.45, 0.65, "stress", ["exhausted", "drained"]),

    # ── Day 3 ─────────────────────────────────────────────────────────────────
    (3, "journal", "user",
     "Took myself out for lunch alone. Sat by the window and watched people. Felt oddly peaceful.",
     "text", None, 0.45, 0.4, "positive", ["relaxed", "content"]),

    (3, "chat", "user",
     "I've been thinking — I spend a lot of energy trying not to be a burden. But maybe that's its own kind of distance.",
     "voice", "s9", -0.2, 0.55, "social", ["lonely", "ashamed"]),
    (3, "chat", "assistant",
     "That's a real insight. Protecting people from your needs is a form of walls. What would it feel like to need something openly?",
     "text", "s9", None, None, None, []),

    # ── Day 1 ─────────────────────────────────────────────────────────────────
    (1, "journal", "user",
     "Couldn't sleep. 3am thoughts. The kind that feel very urgent and very stupid at the same time.",
     "text", None, -0.4, 0.6, "anxiety", ["uneasy", "out_of_control"]),

    # ── Today ─────────────────────────────────────────────────────────────────
    (0, "chat", "user",
     "Not sad exactly. Just quiet inside. Like the volume got turned down on everything.",
     "text", "s10", -0.2, 0.4, "low_mood", ["empty", "lost"]),
    (0, "chat", "assistant",
     "Sometimes quiet isn't emptiness — it's the mind asking for rest. Are you giving yourself permission to just be still today?",
     "text", "s10", None, None, None, []),
    (0, "chat", "user",
     "I'm trying to.",
     "text", "s10", 0.1, 0.3, "positive", ["relaxed"]),
]


def seed() -> None:
    init_db()
    with _conn() as c:
        removed = _wipe(c)
        if removed:
            print(f"Wiped {removed} journal_entries (and mood_snapshots).")

        now = datetime.now(timezone.utc)
        inserted = 0
        for row in _SEED:
            days_ago, mode, role, content, source, session, valence, intensity, category, sub_tags = row
            # spread entries within a day by hour so ordering is natural
            hour = 8 + (inserted % 3) * 4
            ts = (now - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0)
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            cur = c.execute(
                "INSERT INTO journal_entries(created_at, mode, role, content, source, session_id) VALUES (?,?,?,?,?,?)",
                (ts_str, mode, role, content, source, session),
            )
            entry_id = cur.lastrowid

            if role == "user" and valence is not None:
                c.execute(
                    "INSERT INTO mood_snapshots(entry_id, created_at, valence, intensity, category, sub_tags) VALUES (?,?,?,?,?,?)",
                    (entry_id, ts_str, valence, intensity, category, json.dumps(sub_tags, ensure_ascii=False)),
                )
            inserted += 1

        print(f"Seeded {inserted} entries across 30 days ({sum(1 for r in _SEED if r[2]=='user' and r[6] is not None)} with mood tags).")


if __name__ == "__main__":
    seed()
