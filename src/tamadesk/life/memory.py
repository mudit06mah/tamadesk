"""The companion's long-term memory, in three layers. The distilled memory lives in plain markdown,
one file per day (<home>/memory/YYYY-MM-DD.md), which the user can read, edit or delete; SQLite only
keeps a search index of it, rebuilt whenever a file changes.


1. raw: every chat message, log line, todo, mail draft and kept item, full-text indexed (`recall`,
   SQLite FTS5 with stemming) the moment it's written. Free and instant.
2. daily digests: once a day the light model distills a finished day into a short summary plus
   standalone facts, each tagged with broader words ("sushi" -> "japanese food, dish, cuisine").
   That enrichment happens once, at write time, so every later search stays a cheap FTS query
   yet still finds "that japanese dish I wanted to try".
3. recall: search across both layers (facts rank first), then read a whole day for detail.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from tamadesk.brain import Brain
from tamadesk.core import db
from tamadesk.core.config import Settings

DIGEST_SCHEMA = {
    "type": "object",
    "required": ["summary", "facts"],
    "properties": {
        "summary": {"type": "string", "description": "2-4 plain sentences: what the user did, decided, wanted"},
        "facts": {"type": "array", "maxItems": 15, "items": {
            "type": "object", "required": ["text", "tags"],
            "properties": {
                "text": {"type": "string", "description": "one standalone sentence, specific names/numbers kept"},
                "tags": {"type": "string", "description": "5-10 broader words a person might later search with: "
                         "categories, synonyms, related concepts (e.g. 'japanese food dish cuisine restaurant')"},
            }}},
    },
}  # fmt: skip
RAW_KINDS = ("chat_user", "chat_assistant", "log", "todo", "mail", "kept")


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def day_text(conn: sqlite3.Connection, day: str, limit: int = 14000) -> str:
    """Everything indexed for one local day, oldest first, as compact lines."""
    labels = {"chat_user": "user said", "chat_assistant": "assistant replied", "log": "logged",
              "todo": "todo", "mail": "email draft", "kept": "saved"}  # fmt: skip
    rows = conn.execute(
        f"SELECT kind, text FROM recall WHERE day = ? AND kind IN ({','.join('?' * len(RAW_KINDS))}) ORDER BY rowid",
        (day, *RAW_KINDS),
    ).fetchall()
    out = "\n".join(f"[{labels[r['kind']]}] {r['text'][:700]}" for r in rows)
    return out[:limit]


def memory_dir(s: Settings) -> Path:
    d = s.home / "memory"
    d.mkdir(exist_ok=True)
    return d


def to_markdown(day: str, summary: str, facts: list[dict]) -> str:
    title = date.fromisoformat(day).strftime("%A %d %B %Y")
    lines = [f"# {title}", "", summary.strip(), "", "## Facts"]
    for f in facts:
        tags = " ".join(f"#{t}" for t in re.findall(r"[\w-]+", f["tags"].lower()))
        lines.append(f"- {f['text'].strip()} {tags}".rstrip())
    return "\n".join(lines) + "\n"


def from_markdown(text: str) -> tuple[str, list[dict]]:
    """(summary, [{text, tags}]) from a day file. Tags are the #words; the rest of a bullet is the fact."""
    head, _, facts = text.partition("## Facts")
    summary = "\n".join(ln for ln in head.splitlines() if ln.strip() and not ln.startswith("#")).strip()
    out = []
    for ln in facts.splitlines():
        if ln.strip().startswith("- "):
            tags = re.findall(r"#([\w-]+)", ln)
            fact = re.sub(r"\s#[\w-]+", "", ln.strip()[2:]).strip()
            if fact:
                out.append({"text": fact, "tags": " ".join(tags)})
    return summary, out


def index_day(conn: sqlite3.Connection, day: str, summary: str, facts: list[dict]) -> None:
    with db.transaction(conn):
        conn.execute("DELETE FROM memories WHERE day = ?", (day,))
        if summary:
            conn.execute("INSERT INTO memories (day, kind, text) VALUES (?, 'digest', ?)", (day, summary))
        conn.executemany("INSERT INTO memories (day, kind, text, tags) VALUES (?, 'fact', ?, ?)",
                         [(day, f["text"], f["tags"]) for f in facts])  # fmt: skip


def sync_files(s: Settings, conn: sqlite3.Connection) -> int:
    """Re-index day files that were added, edited or deleted since last time. Cheap: one stat per file."""
    seen = db.get_profile(conn, "memory_mtimes", {})
    now: dict[str, float] = {}
    changed = 0
    for p in memory_dir(s).glob("????-??-??.md"):
        now[p.stem] = p.stat().st_mtime
        if seen.get(p.stem) != now[p.stem]:
            index_day(conn, p.stem, *from_markdown(p.read_text()))
            changed += 1
    gone = set(seen) - set(now)
    for day in gone:  # a deleted file means: forget that day, and don't re-digest it later
        index_day(conn, day, "", [])
        changed += 1
    if gone:
        db.set_profile(
            conn, "memory_forgotten", sorted(set(db.get_profile(conn, "memory_forgotten", [])) | gone)
        )
    if changed:
        db.set_profile(conn, "memory_mtimes", now)
    return changed


def digest(s: Settings, conn: sqlite3.Connection, brain: Brain, day: str) -> dict | None:
    """Distill one day into a summary + tagged facts, written to its markdown file (then indexed)."""
    text = day_text(conn, day)
    if not text.strip():
        return None
    out = brain.ask(
        f"This is everything from one day ({day}) of a person's work with their assistant. Write their memory "
        "of it: a short summary, and standalone facts worth remembering later (plans, wishes, decisions, names, "
        "things they liked or want to try, what got done). Each fact must make sense on its own a month later; "
        "tag each with broader words someone might search for. Skip small talk.\n\n" + text,
        DIGEST_SCHEMA,
        light=True,
        kind="memory",
    )
    (memory_dir(s) / f"{day}.md").write_text(to_markdown(day, out["summary"], out["facts"]))
    sync_files(s, conn)
    return out


def pending_days(conn: sqlite3.Connection, limit: int = 7) -> list[str]:
    """Finished days with activity but no memory yet, oldest first (days the user deleted stay forgotten)."""
    rows = conn.execute(
        f"""SELECT DISTINCT day FROM recall WHERE day < ? AND kind IN ({",".join("?" * len(RAW_KINDS))})
            AND day NOT IN (SELECT day FROM memories WHERE kind = 'digest') ORDER BY day LIMIT ?""",
        (today(), *RAW_KINDS, limit + 50),
    ).fetchall()
    forgotten = set(db.get_profile(conn, "memory_forgotten", []))
    return [r["day"] for r in rows if r["day"] not in forgotten][:limit]


def fts_query(q: str) -> str:
    """Free text -> an FTS5 expression: any of the words (prefix match). Explicit FTS syntax passes through."""
    if re.search(r'\b(OR|AND|NOT|NEAR)\b|"', q):
        return q
    words = [w for w in re.findall(r"[\w']+", q.lower()) if len(w) > 1]
    return " OR ".join(f'"{w}"*' for w in words) or '""'


def search(
    conn: sqlite3.Connection, q: str, *, since: str = "", until: str = "", limit: int = 12
) -> list[dict]:
    """Best matches across facts, digests and raw history. Facts and digests rank first."""
    try:
        rows = conn.execute(
            """SELECT day, kind, ref, snippet(recall, 0, '[', ']', '…', 18) AS snip,
                      bm25(recall, 1.0, 0.7) + CASE WHEN kind IN ('fact', 'digest') THEN -2 ELSE 0 END AS rank
               FROM recall WHERE recall MATCH ? AND day >= ? AND day <= ? ORDER BY rank LIMIT ?""",
            (fts_query(q), since or "0000", until or "9999", limit),
        ).fetchall()
    except sqlite3.OperationalError:  # a malformed explicit FTS query: retry as plain words
        return search(
            conn, re.sub(r'["()]|\b(OR|AND|NOT|NEAR)\b', " ", q), since=since, until=until, limit=limit
        )
    return [{"day": r["day"], "kind": r["kind"], "text": r["snip"], "ref": r["ref"]} for r in rows]


def day_notes(conn: sqlite3.Connection, day: str) -> dict:
    mem = conn.execute("SELECT kind, text, tags FROM memories WHERE day = ? ORDER BY id", (day,)).fetchall()
    return {
        "day": day,
        "summary": next((m["text"] for m in mem if m["kind"] == "digest"), None),
        "facts": [m["text"] for m in mem if m["kind"] == "fact"],
        "raw": day_text(conn, day, 8000),
    }


def recent(conn: sqlite3.Connection, days: int = 4) -> list[dict]:
    since = (date.fromisoformat(today()) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT day, text FROM memories WHERE kind = 'digest' AND day >= ? ORDER BY day", (since,)
    )
    return [dict(r) for r in rows]


def timeline(conn: sqlite3.Connection, offset: int = 0, limit: int = 14) -> list[dict]:
    """Days with anything in them, newest first: digest, facts and how much happened."""
    days = conn.execute(
        f"""SELECT day, count(*) AS n, sum(kind LIKE 'chat_%') AS chat_lines FROM recall
            WHERE kind IN ({",".join("?" * len(RAW_KINDS))}) GROUP BY day ORDER BY day DESC LIMIT ? OFFSET ?""",
        (*RAW_KINDS, limit, offset),
    ).fetchall()
    out = []
    for d in days:
        notes = conn.execute(
            "SELECT kind, text FROM memories WHERE day = ? ORDER BY id", (d["day"],)
        ).fetchall()
        chats = conn.execute(
            """SELECT DISTINCT c.id, c.title FROM chats c JOIN messages m ON m.chat_id = c.id
               WHERE date(m.created_at, 'localtime') = ? ORDER BY c.id""",
            (d["day"],),
        ).fetchall()
        out.append({
            "day": d["day"], "things": d["n"], "chats": [dict(c) for c in chats],
            "summary": next((n["text"] for n in notes if n["kind"] == "digest"), None),
            "facts": [n["text"] for n in notes if n["kind"] == "fact"],
        })  # fmt: skip
    return out
