"""Deadlines that build pressure: the closer a todo's deadline, the louder the companion gets.

Stages: 0 calm (more than a day), 1 within a day, 2 within 3 hours, 3 within the hour, 4 due or past.
Each stage pings the desktop once (todos.nudged remembers how far it got), the Today row's
countdown changes colour, and the companion's line picks the most pressing todo. The words follow
the user's own answer to "How should your companion nudge you?". Zero tokens.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta

from tamadesk.core import clock

STAGES = [(timedelta(0), 4), (timedelta(hours=1), 3), (timedelta(hours=3), 2), (timedelta(hours=24), 1)]

# {t} is the todo, {left} how long is left ("2h 10m"), {late} how late it is
LINES: dict[str, dict[int, str]] = {
    "gentle": {
        1: '"{t}" is due in {left}. A small start today makes tomorrow easy.',
        2: '"{t}" is due in {left}. Maybe now is a good time?',
        3: '"{t}" is due in {left}. You can do this, one step at a time.',
        4: '"{t}" was due {late} ago. Still worth finishing, or move the deadline?',
    },
    "hype": {
        1: '"{t}" is due in {left}! Let\'s get a head start and crush it!',
        2: '{left} left on "{t}"! This is your moment, let\'s GO!',
        3: 'Final stretch! "{t}" in {left}! You\'ve got this!!',
        4: '"{t}" ran {late} over, but champions finish! Let\'s close it out!',
    },
    "strict": {
        1: '"{t}" is due in {left}. Schedule it now.',
        2: '"{t}": {left} left. Stop what you\'re doing and start.',
        3: '"{t}" is due in {left}. No more delays.',
        4: '"{t}" is {late} late. Finish it or move the deadline. Now.',
    },
    "deadpan": {
        1: '"{t}" is due in {left}. Just mentioning it.',
        2: '"{t}": {left}. The clock continues to exist.',
        3: '"{t}" in {left}. Bold strategy.',
        4: '"{t}" was due {late} ago. Time remains undefeated.',
    },
}


def stage(left: timedelta) -> int:
    """How close a deadline is: 0 calm, 1 within a day, 2 within 3h, 3 within the hour, 4 late."""
    return next((n for limit, n in STAGES if left <= limit), 0)


def tone(nudge: str | None) -> str:
    """The user's free-text answer to "How should your companion nudge you?" -> one of LINES."""
    t = (nudge or "").lower()
    for key, words in (("hype", r"hype|cheer|excit|energ|pump"), ("strict", r"strict|coach|tough|firm|drill|harsh"),
                       ("deadpan", r"deadpan|dry|sarcas|funny|blunt")):  # fmt: skip
        if re.search(words, t):
            return key
    return "gentle"


def human(d: timedelta) -> str:
    """A duration the way people say it: '45m', '2h 30m', '3d'."""
    mins = max(1, int(abs(d).total_seconds() // 60))
    if mins < 60:
        return f"{mins}m"
    if mins < 24 * 60:
        h, m = divmod(mins, 60)
        return f"{h}h" + (f" {m}m" if m and h < 3 else "")
    return f"{mins // (24 * 60)}d"


def line(title: str, due: datetime, now: datetime, style: str) -> str:
    """The companion's nudge about a deadline, in the user's chosen tone."""
    left = due - now
    n = max(stage(left), 1)
    return LINES[style][n].format(t=title[:60], left=human(left), late=human(left))


def most_pressing(conn: sqlite3.Connection, style: str, now: datetime | None = None) -> dict | None:
    """The open todo with the nearest deadline, if it's within a day (or late): for the companion's line."""
    now = now or datetime.now(UTC)
    r = conn.execute(
        "SELECT id, title, due_at FROM todos WHERE status = 'open' AND due_at IS NOT NULL AND kind = 'todo' "
        "ORDER BY due_at LIMIT 1"
    ).fetchone()
    if r is None or (n := stage(clock.utc(r["due_at"]) - now)) == 0:
        return None
    return {"id": r["id"], "stage": n, "text": line(r["title"], clock.utc(r["due_at"]), now, style)}


def due_nudges(conn: sqlite3.Connection, style: str, now: datetime | None = None) -> list[tuple[int, str]]:
    """Todos that just reached a louder stage: one ping each, never twice for the same stage.
    A todo that jumps several stages at once (set late, or the app was off) pings only for where it is now."""
    now = now or datetime.now(UTC)
    out = []
    for r in conn.execute(
        "SELECT * FROM todos WHERE status = 'open' AND due_at IS NOT NULL AND kind = 'todo'"
    ).fetchall():
        n = stage(clock.utc(r["due_at"]) - now)
        if n > r["nudged"]:
            conn.execute("UPDATE todos SET nudged = ? WHERE id = ?", (n, r["id"]))
            out.append((n, line(r["title"], clock.utc(r["due_at"]), now, style)))
    return out
