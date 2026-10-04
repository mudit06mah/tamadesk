"""Desk actions shared by the HTTP API and the assistant's tools: one code path for each."""

from __future__ import annotations

import sqlite3

from tamadesk.core import db
from tamadesk.life import capture, game


def add_todo(conn: sqlite3.Connection, title: str, due: str | None = None) -> int:
    rid = conn.execute("INSERT INTO todos (title, due_at) VALUES (?, ?)", (title, due)).lastrowid
    db.event(conn, "todo_added", ref_id=rid, detail=title)
    return rid


def complete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    row = conn.execute("SELECT title FROM todos WHERE id = ? AND status = 'open'", (todo_id,)).fetchone()
    if row is None:
        return False
    with db.transaction(conn):
        conn.execute("UPDATE todos SET status = 'done', done_at = datetime('now') WHERE id = ?", (todo_id,))
        db.event(conn, "todo_done", ref_id=todo_id, detail=row["title"], xp=game.XP["todo_done"])
    return True


def add_reminder(conn: sqlite3.Connection, text: str, due: str) -> int:
    rid = conn.execute("INSERT INTO reminders (text, due_at) VALUES (?, ?)", (text, due)).lastrowid
    db.event(conn, "reminder_set", ref_id=rid, detail=text)
    return rid


def add_log(conn: sqlite3.Connection, text: str) -> int:
    rid = conn.execute("INSERT INTO log_entries (body) VALUES (?)", (text,)).lastrowid
    db.event(conn, "logged", ref_id=rid, detail=text, xp=game.XP["logged"])
    return rid


def capture_text(conn: sqlite3.Connection, text: str) -> dict:
    """todo … / remind me … / anything else -> log. Returns what was created."""
    c = capture.parse(text)
    due = capture.sql_ts(c.due_at) if c.due_at else None
    with db.transaction(conn):
        if c.kind == "todo":
            rid, xp = add_todo(conn, c.text, due), 0
        elif c.kind == "reminder":
            rid, xp = add_reminder(conn, c.text, due), 0
        else:
            rid, xp = add_log(conn, c.text), game.XP["logged"]
    return {"kind": c.kind, "id": rid, "text": c.text, "due_at": due, "xp": xp, "no_time": c.no_time}


def add_draft(conn: sqlite3.Connection, *, ask: str, subject: str, body: str, to_name: str = "",
              to_email: str = "", email_source: str = "", email_sure: bool = True,
              item_id: int | None = None, parent_id: int | None = None, kind: str = "first") -> int:  # fmt: skip
    """A draft for Mail. A follow-up or reply inherits its thread's recipient and item."""
    if parent_id and (p := conn.execute("SELECT * FROM drafts WHERE id = ?", (parent_id,)).fetchone()):
        to_email, to_name = to_email or p["to_email"], to_name or p["to_name"]
        item_id = item_id or p["item_id"]
        email_sure = email_sure if to_email != p["to_email"] else True
    to_email = (to_email or "").strip().lower()
    sure = bool(email_sure) or not to_email  # "unsure" only means something when there is an address
    rid = conn.execute(
        """INSERT INTO drafts (ask, subject, body, to_name, to_email, email_source, email_sure, item_id, parent_id, kind)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (ask, subject, body, to_name, to_email, email_source, int(sure), item_id, parent_id, kind),
    ).lastrowid
    db.event(conn, "drafted", ref_id=rid, detail=subject, xp=game.XP["drafted"])
    return rid
