"""SQLite storage: connection setup, schema migrations, and the event log.

Timestamps are stored as SQLite's `datetime('now')` (UTC, 'YYYY-MM-DD HH:MM:SS') everywhere, so
plain text comparisons against `datetime(...)` expressions are safe.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Each entry is one migration; PRAGMA user_version tracks how many have run.
# Never edit an applied migration: append a new one.
MIGRATIONS: list[str] = [
    # 1: profile, writing samples, daily log, todos, reminders, drafts, events
    """
    CREATE TABLE profile (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,          -- JSON
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE samples (
        id         INTEGER PRIMARY KEY,
        kind       TEXT NOT NULL DEFAULT 'email',   -- email|essay|chat|other
        title      TEXT,
        body       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE log_entries (
        id         INTEGER PRIMARY KEY,
        body       TEXT NOT NULL,
        mood       INTEGER,                -- 1..5, optional
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE todos (
        id         INTEGER PRIMARY KEY,
        title      TEXT NOT NULL,
        due_at     TEXT,
        status     TEXT NOT NULL DEFAULT 'open',   -- open|done|dropped
        done_at    TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX todos_status ON todos(status, due_at);

    CREATE TABLE reminders (
        id         INTEGER PRIMARY KEY,
        text       TEXT NOT NULL,
        due_at     TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending',  -- pending|fired|dismissed
        fired_at   TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX reminders_due ON reminders(status, due_at);

    CREATE TABLE drafts (
        id         INTEGER PRIMARY KEY,
        ask        TEXT NOT NULL,
        subject    TEXT,
        body       TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'draft',   -- draft|kept|dropped
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE events (
        id         INTEGER PRIMARY KEY,
        kind       TEXT NOT NULL,          -- todo_done|logged|reminder_set|drafted|recap|...
        ref_id     INTEGER,
        detail     TEXT,
        xp         INTEGER NOT NULL DEFAULT 0,
        at         TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX events_at ON events(at);
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI runs sync dependencies and handlers in different worker threads
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.execute("BEGIN")
        try:
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return conn.execute("PRAGMA user_version").fetchone()[0]


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def event(conn: sqlite3.Connection, kind: str, *, ref_id: int | None = None, detail: str = "",
          xp: int = 0) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO events (kind, ref_id, detail, xp) VALUES (?, ?, ?, ?)", (kind, ref_id, detail, xp)
    )


def get_profile(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM profile WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_profile(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        """INSERT INTO profile (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')""",
        (key, json.dumps(value)),
    )
