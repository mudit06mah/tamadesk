"""XP, levels and streaks, all derived from the `events` table."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

XP = {
    "todo_done": 10,
    "logged": 5,
    "reminder_done": 3,
    "drafted": 5,
    "recap": 10,
    "new_game": 50,
    "triaged": 1,  # saving or skipping an item in a module tab
}


def level_for(xp: int) -> tuple[int, int, int]:
    """(level, xp into this level, xp needed for this level). Level n costs 100 + 50(n-1)."""
    level, need = 1, 100
    while xp >= need:
        xp -= need
        level += 1
        need = 100 + 50 * (level - 1)
    return level, xp, need


def local_day(ts: str) -> date:
    """SQLite UTC 'YYYY-MM-DD HH:MM:SS' -> the user's local calendar day."""
    return datetime.fromisoformat(ts).replace(tzinfo=UTC).astimezone().date()


def streak(days: set[date], today: date) -> int:
    """Consecutive days with activity, ending today (or yesterday, so the streak survives until
    you've had a chance to act today)."""
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def progress(conn: sqlite3.Connection) -> dict:
    xp = conn.execute("SELECT COALESCE(SUM(xp), 0) FROM events").fetchone()[0]
    level, into, need = level_for(xp)
    rows = conn.execute(
        "SELECT at FROM events WHERE xp > 0 AND at >= datetime('now', '-120 days')"
    ).fetchall()
    days = {local_day(r["at"]) for r in rows}
    today = datetime.now().astimezone().date()
    return {"xp": xp, "level": level, "level_xp": into, "level_need": need,
            "streak_days": streak(days, today), "xp_rules": XP}  # fmt: skip
