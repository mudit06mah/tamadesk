"""Desk actions shared by the HTTP API, the assistant's tools and the CLI: one code path for each."""

from __future__ import annotations

import difflib
import re
import sqlite3
from datetime import UTC, datetime

from tamadesk.core import clock, db
from tamadesk.life import capture, game
from tamadesk.life import repeat as repeating


def _when(ts: str | None) -> str:
    return clock.local_naive(ts).strftime("%a %H:%M") if ts else ""


def add_todo(conn: sqlite3.Connection, title: str, due: str | None = None, *, repeat: str | None = None,
             tags: str = "", kind: str = "todo", who: str | None = None, cal_key: str | None = None,
             ext_uid: str | None = None, chain: int = 0, prev_id: int | None = None,
             series: int | None = None) -> int:  # fmt: skip
    """Add a todo (optionally repeating, tagged, waiting on someone, from a calendar event). Returns its id."""
    rid = conn.execute(
        """INSERT INTO todos (title, due_at, repeat, tags, kind, who, cal_key, ext_uid, chain, prev_id, series)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (title, due, repeat, tags, kind, who, cal_key, ext_uid, chain, prev_id, series),
    ).lastrowid
    if repeat and series is None:  # a new habit is its own series
        conn.execute("UPDATE todos SET series = ? WHERE id = ?", (rid, rid))
    db.event(conn, "waiting_added" if kind == "waiting" else "todo_added", ref_id=rid, detail=title)
    return rid


def find_todo(conn: sqlite3.Connection, words: str) -> sqlite3.Row | None:
    """The open todo someone means by a few words ("done invoice", "move the deck to fri")."""
    q = [
        w for w in re.findall(r"\w+", words.lower()) if len(w) > 1 and w not in ("the", "my", "a", "an", "to")
    ]
    best, best_score = None, 0.0
    for t in conn.execute("SELECT * FROM todos WHERE status = 'open' ORDER BY id DESC"):
        title = t["title"].lower()
        hits = sum(1 for w in q if re.search(rf"\b{re.escape(w[:5])}", title))
        score = hits / len(q) if q else 0
        score += difflib.SequenceMatcher(None, words.lower(), title).ratio() * 0.3  # breaks ties
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= 0.6 else None


def _next_repeat(conn: sqlite3.Connection, row: sqlite3.Row, chain: int) -> str | None:
    """Make the next occurrence of a repeating todo, unless its series already has an open one
    (a series never has two). Returns its due time."""
    series = row["series"] or row["id"]
    other = conn.execute(
        "SELECT due_at FROM todos WHERE series = ? AND status = 'open' AND id != ?", (series, row["id"])
    ).fetchone()
    if other:
        return other["due_at"]
    now = datetime.now(UTC).astimezone().replace(tzinfo=None)
    due = clock.local_naive(row["due_at"]) if row["due_at"] else now
    nxt = repeating.next_after(row["repeat"], max(now, due), (due.hour, due.minute))
    nxt_s = clock.sql_ts(clock.to_utc(nxt))
    add_todo(conn, row["title"], nxt_s, repeat=row["repeat"], tags=row["tags"], chain=chain, prev_id=row["id"],
             series=series)  # fmt: skip
    return nxt_s


def complete_todo(conn: sqlite3.Connection, todo_id: int) -> dict:
    """Tick a todo. Returns {xp, chain, milestone, next_due}, or {} if it wasn't open.
    Beating a deadline adds a bonus; a repeating todo grows its habit chain and makes the next one."""
    row = conn.execute(
        """SELECT *, due_at >= datetime('now') AS on_time, due_at >= datetime('now', '-1 day') AS in_grace
           FROM todos WHERE id = ? AND status = 'open'""",
        (todo_id,),
    ).fetchone()
    if row is None:
        return {}
    out = {"xp": 0, "chain": 0, "milestone": False, "next_due": None}
    with db.transaction(conn):
        conn.execute("UPDATE todos SET status = 'done', done_at = datetime('now') WHERE id = ?", (todo_id,))
        if row["kind"] == "waiting":  # it arrived: your part was the chasing
            db.event(conn, "waiting_done", ref_id=todo_id, detail=row["title"], xp=game.XP["waiting_done"])
            return out | {"xp": game.XP["waiting_done"]}
        out["xp"] = game.XP["todo_done"]
        db.event(conn, "todo_done", ref_id=todo_id, detail=row["title"], xp=out["xp"])
        if row["due_at"] and row["on_time"]:
            db.event(conn, "todo_on_time", ref_id=todo_id, detail=row["title"], xp=game.XP["on_time"])
            out["xp"] += game.XP["on_time"]
        if row["repeat"]:
            chain = row["chain"] + 1 if (not row["due_at"] or row["in_grace"]) else 1
            conn.execute("UPDATE todos SET chain = ? WHERE id = ?", (chain, todo_id))
            out |= {
                "chain": chain,
                "milestone": repeating.milestone(chain),
                "next_due": _next_repeat(conn, row, chain),
            }
    return out


def undo_xp(conn: sqlite3.Connection, todo_id: int) -> int:
    """All the XP a todo is still holding (done, on-time bonus, waiting), so undo can take it all back."""
    return conn.execute(
        "SELECT coalesce(sum(xp), 0) FROM events WHERE ref_id = ? AND kind IN ('todo_done', 'todo_on_time', "
        "'waiting_done', 'todo_undone')",
        (todo_id,),
    ).fetchone()[0]


def undo_todo(conn: sqlite3.Connection, todo_id: int) -> int:
    """Reopen a finished or dropped todo: its XP goes back, and the next copy of its series goes away,
    so a series always has exactly one open copy."""
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if row is None or row["status"] == "open":
        return 0
    with db.transaction(conn):
        conn.execute("UPDATE todos SET status = 'open', done_at = NULL WHERE id = ?", (todo_id,))
        if row["series"]:
            conn.execute(
                "DELETE FROM todos WHERE series = ? AND status = 'open' AND id != ?", (row["series"], todo_id)
            )
        conn.execute("DELETE FROM todos WHERE prev_id = ? AND status = 'open'", (todo_id,))
        xp = -undo_xp(conn, todo_id) if row["status"] == "done" else 0
        db.event(conn, "todo_undone", ref_id=todo_id, detail=row["title"], xp=xp)
    return xp


def drop_todo(conn: sqlite3.Connection, todo_id: int, *, stop: bool = False) -> bool:
    """Remove a todo. For a repeating one, `stop` ends the whole series; otherwise it only skips this
    time (the next one comes, and the chain restarts). Returns whether anything changed."""
    row = conn.execute("SELECT * FROM todos WHERE id = ? AND status = 'open'", (todo_id,)).fetchone()
    if row is None:
        return False
    with db.transaction(conn):
        if row["repeat"] and stop:
            conn.execute("UPDATE todos SET status = 'dropped' WHERE series = ? AND status = 'open'",
                         (row["series"] or todo_id,))  # fmt: skip
            db.event(conn, "todo_stopped", ref_id=todo_id, detail=row["title"])
            return True
        conn.execute("UPDATE todos SET status = 'dropped' WHERE id = ?", (todo_id,))
        db.event(conn, "todo_dropped", ref_id=todo_id, detail=row["title"])
        if row["repeat"]:
            _next_repeat(conn, row, 0)
    return True


def cancel_reminder(conn: sqlite3.Connection, reminder_id: int) -> bool:
    """Cancel a reminder before it rings (no XP: nothing was done). A repeating one stops for good."""
    row = conn.execute(
        "SELECT * FROM reminders WHERE id = ? AND status != 'dismissed'", (reminder_id,)
    ).fetchone()
    if row is None:
        return False
    with db.transaction(conn):
        conn.execute("UPDATE reminders SET status = 'dismissed' WHERE id = ?", (reminder_id,))
        db.event(conn, "reminder_cancelled", ref_id=reminder_id, detail=row["text"])
    return True


def find_reminder(conn: sqlite3.Connection, words: str) -> sqlite3.Row | None:
    """A pending reminder someone means by a few words ("cancel the stretch reminder")."""
    q = [w for w in re.findall(r"\w+", words.lower()) if len(w) > 2 and w not in ("the", "my", "reminder")]
    for r in conn.execute("SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at"):
        if q and all(re.search(rf"\b{re.escape(w[:5])}", r["text"].lower()) for w in q):
            return r
    return None


def set_repeat(conn: sqlite3.Connection, todo_id: int, rule: str | None) -> None:
    """Change or stop how an open todo repeats."""
    conn.execute("UPDATE todos SET repeat = ? WHERE id = ? AND status = 'open'", (rule, todo_id))


def set_due(conn: sqlite3.Connection, todo_id: int, when: str) -> str | None:
    """Give a todo a deadline in plain words ('fri 5pm', 'in 2 days', 'tomorrow') or as a local
    'YYYY-MM-DD HH:MM' (the clock picker); '' clears it.
    Returns the new due time (UTC) or None. Raises ValueError if it isn't a time to come."""
    due = None
    if when.strip():
        now = datetime.now(UTC).astimezone().replace(tzinfo=None)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", when.strip()):
            at = datetime.fromisoformat(when.strip())
            at = at if at > now else None
        else:
            _, at = capture.find_time(when.strip(), now)
            at = capture.day_only(at, when, capture.DEFAULT_AT["todo"])
        if at is None:
            raise ValueError(f"couldn't read {when!r} as a time to come, try 'fri 5pm' or 'in 2 days'")
        due = clock.sql_ts(clock.to_utc(at))
    with db.transaction(conn):
        conn.execute(
            "UPDATE todos SET due_at = ?, nudged = 0 WHERE id = ? AND status = 'open'", (due, todo_id)
        )
        db.event(conn, "todo_due", ref_id=todo_id, detail=due or "no deadline")
    return due


def add_reminder(conn: sqlite3.Connection, text: str, due: str, repeat: str | None = None) -> int:
    """Ring at `due` (UTC); `repeat` rings again on the same rule."""
    rid = conn.execute(
        "INSERT INTO reminders (text, due_at, repeat) VALUES (?, ?, ?)", (text, due, repeat)
    ).lastrowid
    db.event(conn, "reminder_set", ref_id=rid, detail=text)
    return rid


def add_log(conn: sqlite3.Connection, text: str, tags: str = "") -> int:
    """A line for today's log."""
    rid = conn.execute("INSERT INTO log_entries (body, tags) VALUES (?, ?)", (text, tags)).lastrowid
    db.event(conn, "logged", ref_id=rid, detail=text, xp=game.XP["logged"])
    return rid


def whats_next(conn: sqlite3.Connection) -> str:
    """The one thing to do now, answered from the desk itself (no AI)."""
    from tamadesk.life import today

    v = today.day(conn)
    if (p := v["pressure"]) and p["stage"] >= 2:
        return p["text"]
    if v["needs_you"]:
        return f"Next: {v['needs_you'][0]['title']}"
    now = clock.sql_ts(datetime.now(UTC).replace(tzinfo=None))
    soon = [
        e for e in v["timeline"] if e["state"] == "open" and (e["at"] or "") >= now and e["kind"] != "recap"
    ]
    if soon:
        return f"Next: {soon[0]['title']} at {clock.local_naive(soon[0]['at']).strftime('%H:%M')}"
    if mine := [e for e in v["anytime"] if not e.get("waiting")]:
        return f"Pick this one: {mine[0]['title']}"
    return "Nothing's waiting on you. Log a win, or take a break ^_^"


def capture_text(conn: sqlite3.Connection, text: str, source: str = "desk") -> dict:
    """The free shortcuts (see life/capture.py). Returns what happened, with a line to show."""
    from tamadesk.life import calendar, focus

    c = capture.parse(text)
    due = clock.sql_ts(c.due_at) if c.due_at else None
    tags = " ".join(c.tags)
    out = {
        "kind": c.kind,
        "id": None,
        "text": c.text,
        "due_at": due,
        "xp": 0,
        "no_time": c.no_time,
        "message": "",
    }
    if source != "desk":  # captured from the terminal or by mail: the quest log notices
        db.event(conn, f"captured_{source}", detail=text[:80])
    if c.kind in ("todo", "reminder", "log", "waiting"):
        with db.transaction(conn):
            if c.kind == "todo":
                out["id"] = add_todo(conn, c.text, due, repeat=c.repeat, tags=tags)
                out["message"] = "todo" + (f", {repeating.label(c.repeat)}" if c.repeat else "") + (
                    f", due {_when(due)}" if due else "")  # fmt: skip
            elif c.kind == "reminder":
                out["id"] = add_reminder(conn, c.text, due, c.repeat)
                out["message"] = f"I'll ring {_when(due)}" + (
                    f", {repeating.label(c.repeat)}" if c.repeat else ""
                )
            elif c.kind == "waiting":
                out["id"] = add_todo(conn, c.text, due, kind="waiting", who=c.who, tags=tags)
                out["message"] = f"waiting on {c.who or 'it'}: I'll nudge you {_when(due)}"
            else:
                out |= {"id": add_log(conn, c.text, tags), "xp": game.XP["logged"]}
        return out
    if c.kind == "done":
        t = find_todo(conn, c.target or "")
        if t is None:  # nothing to tick: it's still something you did
            with db.transaction(conn):
                out |= {"kind": "log", "id": add_log(conn, c.target or "", tags), "xp": game.XP["logged"]}
            return out | {"message": "no open todo like that, so it's in today's log"}
        r = complete_todo(conn, t["id"])
        return out | {"id": t["id"], "text": t["title"], "xp": r.get("xp", 0), "chain": r.get("chain", 0),
                      "milestone": r.get("milestone", False), "message": f"done: {t['title']}"}  # fmt: skip
    if c.kind == "remove":  # a todo first (a repeating one stops for good), else a reminder
        if t := find_todo(conn, c.target or ""):
            drop_todo(conn, t["id"], stop=True)
            return out | {"id": t["id"], "text": t["title"],
                          "message": f"removed: {t['title']}" + (" (it won't repeat)" if t["repeat"] else "")}  # fmt: skip
        if r := find_reminder(conn, c.target or ""):
            cancel_reminder(conn, r["id"])
            return out | {"id": r["id"], "text": r["text"], "message": f"reminder cancelled: {r['text']}"}
        return out | {"message": f"couldn't find a todo or reminder like {c.target!r}"}
    if c.kind == "move":
        t = find_todo(conn, c.target or "")
        if t is None or due is None:
            return out | {
                "message": "couldn't find that todo" if t is None else f"couldn't read {c.text!r} as a time"
            }
        with db.transaction(conn):
            conn.execute("UPDATE todos SET due_at = ?, nudged = 0 WHERE id = ?", (due, t["id"]))
            db.event(conn, "todo_due", ref_id=t["id"], detail=due)
        return out | {"id": t["id"], "text": t["title"], "message": f"moved {t['title']} to {_when(due)}"}
    if c.kind == "meeting":
        out["id"] = calendar.add_local(conn, c.text, c.due_at, c.minutes or 30)
        return out | {
            "message": f"{c.text} at {clock.local_naive(due).strftime('%a %H:%M')}: I'll ring before it"
        }
    if c.kind == "focus":
        f = focus.start(conn, c.minutes or 25, c.tags[0] if c.tags else "")
        return out | {
            "id": f["id"],
            "message": f"focus {f['minutes']} min" + (f" #{f['tag']}" if f["tag"] else ""),
        }
    db.event(conn, "asked_next")  # the tip for "next" retires once it's been used
    return out | {"message": whats_next(conn)}  # next


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
