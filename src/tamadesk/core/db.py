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
    # 2: modules: items from each tab's sources, the local taste model, last run per module
    """
    CREATE TABLE items (
        id           INTEGER PRIMARY KEY,
        module       TEXT NOT NULL,
        ext_id       TEXT NOT NULL,
        source       TEXT NOT NULL,
        title        TEXT NOT NULL,
        subtitle     TEXT,
        body         TEXT,
        url          TEXT,
        data         TEXT,                  -- JSON: source extras, cached summary
        score        REAL NOT NULL DEFAULT 0,
        why          TEXT,                  -- JSON list of the words that ranked it up
        status       TEXT NOT NULL DEFAULT 'new',  -- new|saved|skipped|done
        reason       TEXT,
        published_at TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        decided_at   TEXT,
        UNIQUE (module, ext_id)
    );
    CREATE INDEX items_module ON items(module, status, score);

    CREATE TABLE terms (
        module TEXT NOT NULL,
        term   TEXT NOT NULL,
        pos    INTEGER NOT NULL DEFAULT 0,
        neg    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (module, term)
    );

    CREATE TABLE module_runs (
        module     TEXT PRIMARY KEY,
        last_run   TEXT,
        last_error TEXT,
        added      INTEGER
    );
    """,
    # 3: the assistant (chats + messages), usage accounting, and mail on drafts
    """
    CREATE TABLE chats (
        id         INTEGER PRIMARY KEY,
        session_id TEXT,                    -- Claude Code session, resumed for follow-ups
        title      TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE messages (
        id         INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        role       TEXT NOT NULL,           -- user|assistant
        text       TEXT NOT NULL,
        steps      TEXT,                    -- JSON: tools the assistant used
        cost_usd   REAL,
        tokens     INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX messages_chat ON messages(chat_id, id);
    CREATE TABLE usage (
        id       INTEGER PRIMARY KEY,
        kind     TEXT NOT NULL,             -- ask|agent_tab|summary|author|draft|voice|recap
        cost_usd REAL NOT NULL DEFAULT 0,
        tokens   INTEGER NOT NULL DEFAULT 0,
        at       TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX usage_at ON usage(at);
    ALTER TABLE drafts ADD COLUMN to_name TEXT;
    ALTER TABLE drafts ADD COLUMN to_email TEXT;
    ALTER TABLE drafts ADD COLUMN email_source TEXT;
    ALTER TABLE drafts ADD COLUMN email_sure INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE drafts ADD COLUMN item_id INTEGER;
    ALTER TABLE drafts ADD COLUMN sent_at TEXT;
    ALTER TABLE drafts ADD COLUMN error TEXT;
    """,
    # 4: documents the assistant can read when a task needs them (resume, product brief, …)
    """
    CREATE TABLE docs (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL,
        kind       TEXT NOT NULL DEFAULT 'other',   -- resume|product|notes|other
        text       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
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
