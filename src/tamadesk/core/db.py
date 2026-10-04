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
    # 5: memory. Everything said or done is full-text indexed (recall), and each day is distilled
    # into a short digest plus standalone facts tagged with broader words, so a later search for
    # "that japanese dish" finds "wants to try sushi" without embeddings.
    """
    CREATE TABLE memories (
        id         INTEGER PRIMARY KEY,
        day        TEXT NOT NULL,           -- local YYYY-MM-DD
        kind       TEXT NOT NULL,           -- digest|fact
        text       TEXT NOT NULL,
        tags       TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX memories_day ON memories(day, kind);

    CREATE VIRTUAL TABLE recall USING fts5(
        text, tags, kind UNINDEXED, ref UNINDEXED, day UNINDEXED, tokenize = 'porter unicode61'
    );

    CREATE TRIGGER recall_msg AFTER INSERT ON messages BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.text, '', 'chat_' || new.role, 'm:' || new.id || ':' || new.chat_id, date(new.created_at, 'localtime'));
    END;
    CREATE TRIGGER recall_msg_del AFTER DELETE ON messages BEGIN
        DELETE FROM recall WHERE ref = 'm:' || old.id || ':' || old.chat_id;
    END;
    CREATE TRIGGER recall_log AFTER INSERT ON log_entries BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.body, '', 'log', 'l:' || new.id, date(new.created_at, 'localtime'));
    END;
    CREATE TRIGGER recall_todo AFTER INSERT ON todos BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.title, '', 'todo', 't:' || new.id, date(new.created_at, 'localtime'));
    END;
    CREATE TRIGGER recall_mail AFTER INSERT ON drafts BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.subject || ' ' || coalesce(new.to_name, '') || ' ' || new.body, '', 'mail', 'd:' || new.id,
                date(new.created_at, 'localtime'));
    END;
    CREATE TRIGGER recall_kept AFTER UPDATE OF status ON items WHEN new.status = 'saved' BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.title || ' ' || coalesce(new.body, ''), new.module, 'kept', 'i:' || new.id, date('now', 'localtime'));
    END;
    CREATE TRIGGER recall_mem AFTER INSERT ON memories BEGIN
        INSERT INTO recall (text, tags, kind, ref, day) VALUES (new.text, new.tags, new.kind, 'k:' || new.id, new.day);
    END;
    CREATE TRIGGER recall_mem_del AFTER DELETE ON memories BEGIN
        DELETE FROM recall WHERE ref = 'k:' || old.id;
    END;

    INSERT INTO recall (text, tags, kind, ref, day)
        SELECT text, '', 'chat_' || role, 'm:' || id || ':' || chat_id, date(created_at, 'localtime') FROM messages;
    INSERT INTO recall (text, tags, kind, ref, day)
        SELECT body, '', 'log', 'l:' || id, date(created_at, 'localtime') FROM log_entries;
    INSERT INTO recall (text, tags, kind, ref, day)
        SELECT title, '', 'todo', 't:' || id, date(created_at, 'localtime') FROM todos;
    INSERT INTO recall (text, tags, kind, ref, day)
        SELECT subject || ' ' || coalesce(to_name, '') || ' ' || body, '', 'mail', 'd:' || id, date(created_at, 'localtime')
        FROM drafts;
    INSERT INTO recall (text, tags, kind, ref, day)
        SELECT title || ' ' || coalesce(body, ''), module, 'kept', 'i:' || id, date(coalesce(decided_at, created_at), 'localtime')
        FROM items WHERE status = 'saved';
    """,
    # 6: journeys. Items get a pipeline stage; drafts become threads; the inbox keeps only mail that
    # belongs to something the user started (replies in their threads, news from their pipeline).
    """
    ALTER TABLE items ADD COLUMN stage TEXT;      -- emailed|applied|replied|interview|rejected|done
    ALTER TABLE items ADD COLUMN stage_at TEXT;
    ALTER TABLE drafts ADD COLUMN message_id TEXT;
    ALTER TABLE drafts ADD COLUMN parent_id INTEGER;
    ALTER TABLE drafts ADD COLUMN kind TEXT NOT NULL DEFAULT 'first';   -- first|followup|reply
    ALTER TABLE drafts ADD COLUMN followup_off INTEGER NOT NULL DEFAULT 0;

    CREATE TABLE inbox (
        id          INTEGER PRIMARY KEY,
        message_id  TEXT UNIQUE,
        draft_id    INTEGER,                -- the sent mail this answers, if any
        item_id     INTEGER,                -- the job/lead it's about, if any
        kind        TEXT NOT NULL,          -- reply|applied|interview|rejected|bounce|update
        from_addr   TEXT,
        from_name   TEXT,
        subject     TEXT,
        snippet     TEXT,
        received_at TEXT,
        status      TEXT NOT NULL DEFAULT 'new',   -- new|done
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX inbox_status ON inbox(status, kind);

    CREATE TRIGGER recall_inbox AFTER INSERT ON inbox BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (coalesce(new.from_name, new.from_addr) || ': ' || coalesce(new.subject, '') || ' ' || coalesce(new.snippet, ''),
                new.kind, 'mail_in', 'n:' || new.id, date(new.created_at, 'localtime'));
    END;
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
    """Apply pending migrations, each atomically. Returns the resulting schema version.
    executescript (not a split on ';') so migrations can hold triggers with BEGIN … END bodies."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
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
