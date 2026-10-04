"""Desk actions shared by the HTTP API and the assistant's tools: one code path for each."""

from __future__ import annotations

import sqlite3

from tamadesk.core import db
from tamadesk.life import capture, game


def add_todo(conn: sqlite3.Connection, title: str, due: str | None = None) -> int:
    rid = conn.execute("INSERT INTO todos (title, due_at) VALUES (?, ?)", (title, due)).lastrowid
    db.event(conn, "todo_added", ref_id=rid, detail=title)
    return rid


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
    return {"kind": c.kind, "id": rid, "text": c.text, "due_at": due, "xp": xp}


def add_draft(conn: sqlite3.Connection, *, ask: str, subject: str, body: str, to_name: str = "",
              to_email: str = "", email_source: str = "", email_sure: bool = True,
              item_id: int | None = None) -> int:  # fmt: skip
    rid = conn.execute(
        """INSERT INTO drafts (ask, subject, body, to_name, to_email, email_source, email_sure, item_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ask, subject, body, to_name, to_email.strip().lower(), email_source, int(email_sure), item_id),
    ).lastrowid
    db.event(conn, "drafted", ref_id=rid, detail=subject, xp=game.XP["drafted"])
    return rid
