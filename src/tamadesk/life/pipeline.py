"""Where a job or lead stands: kept -> emailed/applied -> replied/interview -> rejected/done.

Stages move forward on real events (a send, a reply, a portal email). The user can always set one
by hand, including moving it back. Every change is an event, so memory and recaps see it.
"""

from __future__ import annotations

import sqlite3

from tamadesk.core import db

ORDER = ["emailed", "applied", "replied", "interview", "rejected", "done"]


def set_stage(
    conn: sqlite3.Connection, item_id: int | None, stage: str, *, why: str = "", manual: bool = False
) -> bool:
    """Move an item to `stage`. Automatic moves only go forward (a late 'thanks for applying' never
    undoes a reply); manual ones go anywhere. Returns whether it changed."""
    if item_id is None or stage not in ORDER:
        return False
    row = conn.execute("SELECT stage, title FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None or row["stage"] == stage:
        return False
    if not manual and row["stage"] and ORDER.index(stage) < ORDER.index(row["stage"]):
        return False
    conn.execute("UPDATE items SET stage = ?, stage_at = datetime('now') WHERE id = ?", (stage, item_id))
    db.event(
        conn, f"stage_{stage}", ref_id=item_id, detail=f"{row['title'][:80]}{f' ({why})' if why else ''}"
    )
    return True
