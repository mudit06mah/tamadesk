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
    # 7: calendar. Meetings from invites in mail and a private iCal feed, merged on the iCal UID.
    # Only event fields are kept: never the mail body, the description or the attendee list.
    """
    CREATE TABLE cal_events (
        id              INTEGER PRIMARY KEY,
        uid             TEXT NOT NULL,
        recurrence_id   TEXT NOT NULL DEFAULT '',   -- '' for an event or series; else the occurrence it changes (UTC)
        sources         TEXT NOT NULL DEFAULT '',   -- ',mail,' ',feed,' or both
        sequence        INTEGER NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed|tentative|cancelled|gone (left the feed)
        title           TEXT NOT NULL,
        start_at        TEXT NOT NULL,              -- UTC, first occurrence
        end_at          TEXT NOT NULL,
        all_day         INTEGER NOT NULL DEFAULT 0,
        recurring       INTEGER NOT NULL DEFAULT 0,
        until           TEXT,                       -- UTC end of the series, if it has one
        meet_url        TEXT,
        location        TEXT,
        organizer_name  TEXT,
        organizer_email TEXT,
        item_id         INTEGER,                    -- the job/lead it's about, if any
        vevent          TEXT NOT NULL,              -- the event as iCal, stripped to the fields above
        tz              TEXT,                       -- VTIMEZONE blocks it refers to
        updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (uid, recurrence_id)
    );
    CREATE INDEX cal_events_time ON cal_events(start_at, end_at);
    ALTER TABLE reminders ADD COLUMN cal_key TEXT;    -- uid|start for a meeting alert
    CREATE UNIQUE INDEX reminders_cal ON reminders(cal_key);

    CREATE TRIGGER recall_cal AFTER INSERT ON cal_events BEGIN
        INSERT INTO recall (text, tags, kind, ref, day)
        VALUES (new.title || ' ' || coalesce(new.organizer_name, ''), 'meeting calendar', 'meeting', 'c:' || new.id,
                date(new.start_at, 'localtime'));
    END;
    """,
    # 8: "only you" suggestions on mail and drafts. One row per target and rule, so a dismissed one
    # never comes back; XP is in events like everything else.
    """
    CREATE TABLE suggestions (
        id         INTEGER PRIMARY KEY,
        target     TEXT NOT NULL,              -- draft|inbox
        target_id  INTEGER NOT NULL,
        rule       TEXT NOT NULL,              -- direct_question|deadline|guessed_address|why_company|personal_detail|meeting_mention|ai1|ai2
        text       TEXT NOT NULL,
        data       TEXT,                       -- JSON: e.g. {"due": ...} for a deadline
        snapshot   TEXT,                       -- the draft body when it was suggested, to see what changed
        status     TEXT NOT NULL DEFAULT 'open',  -- open|done|dismissed
        auto       INTEGER NOT NULL DEFAULT 1, -- 0 after an undo: don't tick it again on its own
        xp         INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        done_at    TEXT,
        UNIQUE (target, target_id, rule)
    );
    CREATE INDEX suggestions_target ON suggestions(target, target_id, status);
    """,
    # 9: deadlines that build pressure (how far the nudges have gone), and items a tab's fit dropped
    """
    ALTER TABLE todos ADD COLUMN nudged INTEGER NOT NULL DEFAULT 0;   -- 0 none, then 1 day, 2 hours, 3 hour, 4 due
    ALTER TABLE module_runs ADD COLUMN dropped INTEGER;                -- items the last run left out: poor fit
    """,
    # 10: everyday play. Repeating todos and reminders (with habit chains), things you wait on, #tags,
    # promises made in meetings, deadlines from feeds, focus sessions, held notifications, local "seen".
    """
    ALTER TABLE todos ADD COLUMN repeat TEXT;                       -- daily|weekdays|weekly:0,3|monthly:15
    ALTER TABLE todos ADD COLUMN chain INTEGER NOT NULL DEFAULT 0;  -- habit chain: on-time completions in a row
    ALTER TABLE todos ADD COLUMN prev_id INTEGER;                   -- the repeat this one was spawned from
    ALTER TABLE todos ADD COLUMN kind TEXT NOT NULL DEFAULT 'todo'; -- todo|waiting
    ALTER TABLE todos ADD COLUMN who TEXT;                          -- waiting on whom
    ALTER TABLE todos ADD COLUMN tags TEXT NOT NULL DEFAULT '';     -- space separated, no '#'
    ALTER TABLE todos ADD COLUMN cal_key TEXT;                      -- promised in this meeting (uid|start)
    ALTER TABLE todos ADD COLUMN ext_uid TEXT;                      -- from a deadline feed
    CREATE UNIQUE INDEX todos_ext ON todos(ext_uid);
    ALTER TABLE reminders ADD COLUMN repeat TEXT;
    ALTER TABLE log_entries ADD COLUMN tags TEXT NOT NULL DEFAULT '';

    CREATE TABLE focus (
        id         INTEGER PRIMARY KEY,
        tag        TEXT NOT NULL DEFAULT '',
        minutes    INTEGER NOT NULL,
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        ends_at    TEXT NOT NULL,
        ended_at   TEXT,
        status     TEXT NOT NULL DEFAULT 'running'   -- running|done|stopped
    );
    CREATE TABLE meeting_notes (                      -- "anything you promised?" answered for a meeting
        cal_key    TEXT PRIMARY KEY,
        status     TEXT NOT NULL,                     -- added|nothing
        at         TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE pings (                              -- notifications held for quiet hours or focus
        id    INTEGER PRIMARY KEY,
        kind  TEXT NOT NULL,
        title TEXT NOT NULL,
        body  TEXT NOT NULL,
        at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE seen (                               -- things dismissed locally (e.g. GitHub notifications)
        kind  TEXT NOT NULL,
        key   TEXT NOT NULL,
        at    TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (kind, key)
    );
    """,
    # 11: a repeating todo is one series with at most one open copy (finishing or skipping makes the
    # next; undo puts things back), so it can always be stopped as a whole
    """
    ALTER TABLE todos ADD COLUMN series INTEGER;   -- the first todo of a repeating series
    WITH RECURSIVE chain(id, root) AS (
        SELECT id, id FROM todos WHERE prev_id IS NULL
        UNION ALL SELECT t.id, chain.root FROM todos t JOIN chain ON t.prev_id = chain.id
    )
    UPDATE todos SET series = (SELECT root FROM chain WHERE chain.id = todos.id)
    WHERE repeat IS NOT NULL OR prev_id IS NOT NULL;
    """,
    # 12: job search that learns. Company job boards found through search (watched on every refresh),
    # verdicts on companies against the user's preferences (asked once per company), and why a
    # refresh left things out
    """
    CREATE TABLE boards (
        module     TEXT NOT NULL,
        board      TEXT NOT NULL,                 -- "<system>:<company id>", e.g. "greenhouse:acme"
        found_from TEXT,                          -- the posting that revealed it
        added_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (module, board)
    );
    CREATE TABLE companies (
        key        TEXT PRIMARY KEY,              -- lowercased company name or host
        ok         INTEGER NOT NULL,              -- fits the user's preferences
        why        TEXT,
        prefs      TEXT,                          -- the preferences it was judged against (re-asked if they change)
        checked_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    ALTER TABLE module_runs ADD COLUMN left_out TEXT;   -- JSON {"poor fit": 5, "closed": 3, ...}
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    """Open the database (WAL, foreign keys on, waits up to 5s on a lock); migrate() brings the schema up to date."""
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
    """Run a block atomically: commit on success, roll back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def event(conn: sqlite3.Connection, kind: str, *, ref_id: int | None = None, detail: str = "",
          xp: int = 0) -> None:  # fmt: skip
    """Record something that happened. This is the one place XP is given (or taken back, with negative xp)."""
    conn.execute(
        "INSERT INTO events (kind, ref_id, detail, xp) VALUES (?, ?, ?, ?)", (kind, ref_id, detail, xp)
    )


def get_profile(conn: sqlite3.Connection, key: str, default=None):
    """A JSON value from the profile table (about, companion, voice, ...), or `default`."""
    row = conn.execute("SELECT value FROM profile WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_profile(conn: sqlite3.Connection, key: str, value) -> None:
    """Store a JSON value in the profile table."""
    conn.execute(
        """INSERT INTO profile (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')""",
        (key, json.dumps(value)),
    )
