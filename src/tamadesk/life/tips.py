"""Learning the desk by using it: the example chips under the Ask box suggest the shortcuts you haven't
tried yet (a habit, a deadline, a focus session, waiting on someone…). Click one, it fills the box,
and once you've used that kind of thing it makes room for the next. No checklist, no rewards: the
desk just shows you one more thing it can do, when there's room for it.
"""

from __future__ import annotations

import sqlite3

# (what it shows, whether you've already done that kind of thing)
TIPS = [
    ("todo send the invoice fri 5pm", "SELECT 1 FROM todos WHERE due_at IS NOT NULL"),
    ("todo stretch every weekday 11am", "SELECT 1 FROM todos WHERE repeat IS NOT NULL"),
    ("focus 25", "SELECT 1 FROM focus"),
    ("waiting on the specs from Alex by thu", "SELECT 1 FROM todos WHERE kind = 'waiting'"),
    ("meeting design review tomorrow 3pm", "SELECT 1 FROM cal_events"),
    ("done invoice", "SELECT 1 FROM todos WHERE status = 'done'"),
    ("what's next?", "SELECT 1 FROM events WHERE kind = 'asked_next'"),
]


def untried(conn: sqlite3.Connection, limit: int = 2) -> list[str]:
    """The next few shortcuts this person hasn't used yet, in a sensible learning order."""
    return [tip for tip, sql in TIPS if conn.execute(sql).fetchone() is None][:limit]
