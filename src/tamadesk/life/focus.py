"""Focus sessions: the companion sits with you while you work on one thing.

One session at a time. Finishing one earns XP (2 per 5 minutes, so a 25-minute block is +10);
stopping early earns nothing, but the minutes still count as time spent, so the weekly review can
say how long went to each #tag (a client, a project). While a session runs, notifications that can
wait are held (life/notify.py).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from tamadesk.core import db
from tamadesk.life import game


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def xp_for(minutes: int) -> int:
    """XP for a finished session: a little for every 5 minutes."""
    return game.XP["focus_5min"] * (minutes // 5)


def running(conn: sqlite3.Connection) -> dict | None:
    """The focus session in progress, if any."""
    r = conn.execute("SELECT * FROM focus WHERE status = 'running' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def start(conn: sqlite3.Connection, minutes: int, tag: str = "", now: datetime | None = None) -> dict:
    """Start a session (a running one is stopped first: you can only focus on one thing)."""
    now = now or datetime.now(UTC)
    with db.transaction(conn):
        if r := running(conn):
            _end(conn, r, "stopped", now)
        fid = conn.execute(
            "INSERT INTO focus (tag, minutes, started_at, ends_at) VALUES (?, ?, ?, ?)",
            (tag, minutes, _ts(now), _ts(now + timedelta(minutes=minutes))),
        ).lastrowid
    return dict(conn.execute("SELECT * FROM focus WHERE id = ?", (fid,)).fetchone())


def _end(conn: sqlite3.Connection, r: dict, status: str, now: datetime) -> int:
    xp = xp_for(r["minutes"]) if status == "done" else 0
    conn.execute("UPDATE focus SET status = ?, ended_at = ? WHERE id = ?", (status, _ts(now), r["id"]))
    label = f"{r['minutes']} min focus" + (f" #{r['tag']}" if r["tag"] else "")
    db.event(conn, "focus_done" if status == "done" else "focus_stopped", ref_id=r["id"], detail=label, xp=xp)
    return xp


def stop(conn: sqlite3.Connection, now: datetime | None = None) -> dict | None:
    """Stop early: no XP, but the minutes you did focus are kept."""
    r = running(conn)
    if r is None:
        return None
    with db.transaction(conn):
        _end(conn, r, "stopped", now or datetime.now(UTC))
    return r


def finish_due(conn: sqlite3.Connection, now: datetime | None = None) -> dict | None:
    """Close the running session if its time is up. Returns it with its XP, or None."""
    now = now or datetime.now(UTC)
    r = running(conn)
    if r is None or r["ends_at"] > _ts(now):
        return None
    with db.transaction(conn):
        xp = _end(conn, r, "done", datetime.fromisoformat(r["ends_at"]))
    return r | {"xp": xp, "status": "done"}


def minutes_by_tag(conn: sqlite3.Connection, since: str, until: str) -> dict[str, int]:
    """Time actually spent per tag (finished sessions in full, stopped ones up to when they stopped)."""
    out: dict[str, int] = {}
    for r in conn.execute(
        "SELECT tag, minutes, started_at, ended_at, status FROM focus WHERE status != 'running' AND started_at >= ? "
        "AND started_at < ?",
        (since, until),
    ):
        spent = (
            r["minutes"]
            if r["status"] == "done"
            else int(
                (
                    datetime.fromisoformat(r["ended_at"]) - datetime.fromisoformat(r["started_at"])
                ).total_seconds()
                // 60
            )
        )
        out[r["tag"] or "untagged"] = out.get(r["tag"] or "untagged", 0) + max(0, spent)
    return out
