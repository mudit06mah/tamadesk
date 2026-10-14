"""XP, levels and streaks, all derived from the `events` table."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from tamadesk.core import clock

XP = {
    "todo_done": 10,
    "logged": 5,
    "reminder_done": 3,
    "drafted": 5,
    "recap": 10,
    "new_game": 50,
    "triaged": 1,  # saving or skipping an item in a module tab
    "suggestion_done": 3,
    "on_time": 5,  # a todo finished before its deadline
    "focus_5min": 2,  # per 5 minutes of a focus session you finished (25 min = 10)
    "waiting_done": 5,  # something you were waiting on arrived  # an "only you" suggestion the data shows you really did
}


def level_for(xp: int) -> tuple[int, int, int]:
    """(level, xp into this level, xp needed for this level). Level n costs 100 + 50(n-1)."""
    level, need = 1, 100
    while xp >= need:
        xp -= need
        level += 1
        need = 100 + 50 * (level - 1)
    return level, xp, need


FREEZE_EVERY, FREEZE_MAX = 7, 2


def streak_with_freezes(days: set[date], today: date) -> tuple[int, int, list[date]]:
    """(streak, freezes left, days a freeze covered). Every 7 active days in a row earn a freeze (2 at
    most); a missed day spends one instead of breaking the streak. Today never breaks it: it isn't
    over yet. Replayed from the history each time, so nothing is stored and nothing drifts."""
    if not days:
        return 0, 0, []
    d, n, tokens, frozen = min(days), 0, 0, []
    while d <= today:
        if d in days:
            n += 1
            if n % FREEZE_EVERY == 0:
                tokens = min(FREEZE_MAX, tokens + 1)
        elif d != today:
            if n and tokens:
                tokens -= 1
                frozen.append(d)
            else:
                n = 0
        d += timedelta(days=1)
    return n, tokens, frozen


def progress(conn: sqlite3.Connection) -> dict:
    """XP, level, streak and freezes, all replayed from events (nothing stored, so nothing drifts)."""
    xp = conn.execute("SELECT COALESCE(SUM(xp), 0) FROM events").fetchone()[0]
    level, into, need = level_for(xp)
    rows = conn.execute(
        "SELECT at FROM events WHERE xp > 0 AND at >= datetime('now', '-120 days')"
    ).fetchall()
    days = {clock.day_of(r["at"]) for r in rows}
    today = clock.today()
    days_in_a_row, freezes, frozen = streak_with_freezes(days, today)
    return {"xp": xp, "level": level, "level_xp": into, "level_need": need, "streak_days": days_in_a_row,
            "freezes": freezes, "frozen": [d.isoformat() for d in frozen[-3:]], "xp_rules": XP}  # fmt: skip
