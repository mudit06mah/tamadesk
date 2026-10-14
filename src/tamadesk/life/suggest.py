"""Only you: small things on a mail or draft that the user should do themselves.

"Reply today: they asked you a question", "check this guessed address", "add one line about why
this company", "you meet them Thursday, mention it". Each one is a plain regex rule (zero tokens);
Claude is only asked when the user clicks "anything else?" and no rule had something to say.

A suggestion is done (ticked), dismissed (never comes back: one row per target and rule), or open.
XP only comes when the data shows it really happened (a reply was sent, the placeholder is gone),
whether the user ticks it or it resolves on its own; undo takes it back.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from tamadesk.core import clock, db
from tamadesk.life import capture, game

ASKING = re.compile(
    r"\b(?:you|your|could|can|would|will|when|what|which|are|do|does|how|is there|any chance|let me know)\b",
    re.IGNORECASE,
)
DEADLINE = re.compile(
    r"\b(?:by|before|until|no later than|deadline(?: is| of)?|due(?: by| on)?|within|in the next)\s+"
    r"((?:end of (?:the )?(?:day|week)|eod|eow|\w+day|tomorrow|tonight|today|next \w+|\d{1,2}(?:st|nd|rd|th)?"
    r"(?: of)? \w+|\w+ \d{1,2}(?:st|nd|rd|th)?|\d+ (?:hours?|days?|business days?))(?: at [\d:apm ]+)?)",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(r"\[[^\]\n]{2,40}\]|\{[^}\n]{2,40}\}|<[A-Z][^>\n]{1,30}>|\bX{3,}\b|\bTODO\b|\bTBD\b")
STOCK = re.compile(
    r"I hope (?:this|you)(?: email| message)? (?:finds you|are|is) well|I am writing to|To whom it may concern"
    r"|Dear (?:Sir|Madam|Hiring Manager)|I came across your (?:company|profile)",
    re.IGNORECASE,
)
EOD = {"eod": "today 5pm", "end of day": "today 5pm", "end of the day": "today 5pm", "eow": "friday 5pm",
       "end of week": "friday 5pm", "end of the week": "friday 5pm"}  # fmt: skip


# ---------------------------------------------------------------- rules (pure: row in, findings out)


def question(text: str) -> str | None:
    """The first question asked of the reader, if any."""
    for s in re.split(r"(?<=[?.!])\s+", text):
        if s.endswith("?") and ASKING.search(s) and len(s) > 8:
            return s.strip()[-160:]
    return None


def deadline(text: str, received: datetime) -> datetime | None:
    """A date the sender needs something by, read relative to when the mail arrived (naive local)."""
    for m in DEADLINE.finditer(text):
        phrase = EOD.get(m.group(1).lower(), m.group(1))
        phrase = re.sub(r"(\d+) business days?", r"\1 days", phrase)
        if re.match(r"\d+ (?:hours?|days?)", phrase):
            phrase = f"in {phrase}"
        _, when = capture.find_time(phrase, received)
        if when is not None:
            return when
    return None


def company_of(item: sqlite3.Row | None) -> str | None:
    """The company a job or lead item is about, if it says."""
    if item is None:
        return None
    data = json.loads(item["data"] or "{}")
    if data.get("company"):
        return data["company"]
    m = re.search(r"(?:,| at | @ )\s*([A-Z][\w&.\- ]{1,40})$", item["title"] or "")
    return m.group(1).strip() if m else None


def personal(d: sqlite3.Row) -> str | None:
    """What makes a draft read like a template, as an instruction, or None."""
    body = d["body"] or ""
    if m := PLACEHOLDER.search(body):
        return f"Fill in {m.group(0)}: only you know what goes there"
    if m := STOCK.search(body):
        return f'Swap "{m.group(0)}" for one line that\'s about them'
    first = (d["to_name"] or "").split(" ")[0]
    opener = body.strip().split("\n")[0]
    if (
        first
        and len(first) > 1
        and "@" not in first
        and re.match(r"^(?:hi|hello|hey|dear)\b[ ,]*$", opener, re.IGNORECASE)
    ):
        return f"Greet {first} by name"
    return None


def _nice(dt: datetime) -> str:
    return dt.strftime("%a %d %b") + ("" if (dt.hour, dt.minute) == (0, 0) else dt.strftime(" %H:%M"))


def _replied(conn: sqlite3.Connection, m: sqlite3.Row, before: str | None = None) -> bool:
    """Did the user send an answer to this mail (in its thread, or to the same job/lead) after it came?"""
    q = """SELECT 1 FROM drafts WHERE status = 'sent' AND sent_at >= ? AND (
             (parent_id IS NOT NULL AND parent_id = ?) OR (item_id IS NOT NULL AND item_id = ?))"""
    args: list = [m["received_at"] or m["created_at"], m["draft_id"], m["item_id"]]
    if before:
        q += " AND sent_at <= ?"
        args.append(before)
    return conn.execute(q, args).fetchone() is not None


def for_inbox(conn: sqlite3.Connection, m: sqlite3.Row) -> list[tuple[str, str, dict]]:
    """Things only the user can do about a mail: answer a question, meet a deadline."""
    if m["kind"] not in ("reply", "interview", "update"):
        return []
    who = m["from_name"] or m["from_addr"]
    text = m["snippet"] or ""
    out = []
    if q := question(text):
        out.append(("direct_question", f'Reply today: {who} asked "{q}"', {}))
    if due := deadline(text, clock.local_naive(m["received_at"] or m["created_at"])):
        utc = clock.to_utc(due)
        out.append(("deadline", f"{who} needs an answer by {_nice(due)}", {"due": clock.sql_ts(utc)}))
    return out


def for_draft(conn: sqlite3.Connection, d: sqlite3.Row) -> list[tuple[str, str, dict]]:
    """Things only the user can do on a draft: check a guessed address, say why this company, fill a placeholder,
    mention a meeting."""
    out = []
    if not d["email_sure"] and d["to_email"]:
        text = f"Check {d['to_email']} is right before sending: it was guessed, not published"
        out.append(("guessed_address", text, {"source": d["email_source"]}))
    item = (
        conn.execute("SELECT * FROM items WHERE id = ?", (d["item_id"],)).fetchone() if d["item_id"] else None
    )
    company = company_of(item)
    if d["kind"] == "first" and company and company.lower() not in (d["body"] or "").lower():
        out.append(("why_company", f"Add one line about why {company} specifically", {"company": company}))
    if p := personal(d):
        out.append(("personal_detail", p, {}))
    if meet := _meeting_with(conn, d):
        out.append(("meeting_mention", f"You meet {meet['who']} {meet['when']}: mention it", {}))
    return out


def _meeting_with(conn: sqlite3.Connection, d: sqlite3.Row) -> dict | None:
    from tamadesk.life import calendar

    now = datetime.now(UTC)
    for o in calendar.occurrences(conn, clock.sql_ts(now.replace(tzinfo=None)),
                                  clock.sql_ts((now + timedelta(days=3)).replace(tzinfo=None))):  # fmt: skip
        row = conn.execute(
            "SELECT organizer_email, organizer_name FROM cal_events WHERE id = ?", (o["id"],)
        ).fetchone()
        same_item = d["item_id"] and o["item_id"] == d["item_id"]
        same_person = d["to_email"] and row["organizer_email"] == (d["to_email"] or "").lower()
        if o["status"] != "cancelled" and (same_item or same_person):
            return {
                "who": row["organizer_name"] or d["to_name"] or "them",
                "when": _nice(clock.local_naive(o["start"])),
            }
    return None


# ---------------------------------------------------------------- did it really happen?


def _verified(conn: sqlite3.Connection, s: sqlite3.Row) -> bool:
    data = json.loads(s["data"] or "{}")
    if s["target"] == "inbox":
        m = conn.execute("SELECT * FROM inbox WHERE id = ?", (s["target_id"],)).fetchone()
        if m is None:
            return False
        return _replied(conn, m, data.get("due") if s["rule"] == "deadline" else None)
    d = conn.execute("SELECT * FROM drafts WHERE id = ?", (s["target_id"],)).fetchone()
    if d is None:
        return False
    body = (d["body"] or "").lower()
    return {
        "guessed_address": lambda: bool(d["email_sure"]),
        "why_company": lambda: data.get("company", "").lower() in body,
        "personal_detail": lambda: personal(d) is None and (d["body"] or "") != (s["snapshot"] or ""),
    }.get(s["rule"], lambda: False)()


# XP for the ones whose proof is real work; a ticked "check the address" is your word, so it's free
EARNS = {"direct_question", "deadline", "why_company", "personal_detail"}


def _close(conn: sqlite3.Connection, s: sqlite3.Row, verified: bool) -> int:
    xp = game.XP["suggestion_done"] if verified and s["rule"] in EARNS else 0
    conn.execute(
        "UPDATE suggestions SET status = 'done', xp = ?, done_at = datetime('now') WHERE id = ?",
        (xp, s["id"]),
    )
    db.event(conn, "suggestion_done", ref_id=s["id"], detail=s["text"][:120], xp=xp)
    return xp


# ---------------------------------------------------------------- state


def refresh(conn: sqlite3.Connection, target: str, target_id: int) -> None:
    """Run the rules for one mail or draft: add new findings, close the ones that really happened."""
    table = {"draft": "drafts", "inbox": "inbox"}[target]
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (target_id,)).fetchone()
    if row is None:
        return
    rules: Callable = for_draft if target == "draft" else for_inbox
    with db.transaction(conn):
        for rule, text, data in rules(conn, row):
            conn.execute(
                """INSERT INTO suggestions (target, target_id, rule, text, data, snapshot) VALUES (?,?,?,?,?,?)
                   ON CONFLICT (target, target_id, rule) DO NOTHING""",
                (target, target_id, rule, text, json.dumps(data), row["body"] if target == "draft" else None),
            )
        for s in conn.execute(
            "SELECT * FROM suggestions WHERE target = ? AND target_id = ? AND status = 'open' AND auto = 1",
            (target, target_id),
        ).fetchall():
            if _verified(conn, s):
                _close(conn, s, True)


def open_for(conn: sqlite3.Connection, target: str, target_id: int) -> list[dict]:
    """Open suggestions for a mail or draft, after re-running the rules (some resolve on their own)."""
    refresh(conn, target, target_id)
    rows = conn.execute(
        "SELECT id, rule, text, data FROM suggestions WHERE target = ? AND target_id = ? AND status = 'open' ORDER BY id",
        (target, target_id),
    )
    return [
        dict(r) | {"data": json.loads(r["data"] or "{}"), "required": r["rule"] == "guessed_address"}
        for r in rows
    ]


def asked(conn: sqlite3.Connection, target: str, target_id: int) -> bool:
    """Whether Claude was already asked about this one (so "anything else?" shows once)."""
    return conn.execute("SELECT 1 FROM suggestions WHERE target = ? AND target_id = ? AND rule LIKE 'ai%'",
                        (target, target_id)).fetchone() is not None  # fmt: skip


def act(conn: sqlite3.Connection, sid: int, action: str) -> dict:
    """done | undo | dismiss. Returns the XP change (for the +XP float)."""
    s = conn.execute("SELECT * FROM suggestions WHERE id = ?", (sid,)).fetchone()
    if s is None:
        raise KeyError(sid)
    with db.transaction(conn):
        if action == "done" and s["status"] == "open":
            if s["rule"] == "guessed_address":  # the same promise as the "I checked this address" box
                conn.execute("UPDATE drafts SET email_sure = 1 WHERE id = ?", (s["target_id"],))
            return {"xp": _close(conn, s, _verified(conn, s) or s["rule"] == "guessed_address")}
        if action == "undo" and s["status"] == "done":
            conn.execute(
                "UPDATE suggestions SET status = 'open', xp = 0, done_at = NULL, auto = 0 WHERE id = ?",
                (sid,),
            )
            db.event(conn, "suggestion_undone", ref_id=sid, detail=s["text"][:120], xp=-s["xp"])
            return {"xp": -s["xp"]}
        if action == "undo" and s["status"] == "dismissed":  # a misclick: it comes back
            conn.execute("UPDATE suggestions SET status = 'open' WHERE id = ?", (sid,))
            return {"xp": 0}
        if action == "dismiss" and s["status"] == "open":
            if s["rule"] == "guessed_address":
                raise ValueError("check the address instead: a guessed one can't be sent unchecked")
            conn.execute("UPDATE suggestions SET status = 'dismissed' WHERE id = ?", (sid,))
    return {"xp": 0}


def remind(conn: sqlite3.Connection, sid: int) -> str:
    """For a deadline: a reminder a day before (or 2 hours before, if it's sooner than that)."""
    from tamadesk.life import actions

    s = conn.execute("SELECT * FROM suggestions WHERE id = ?", (sid,)).fetchone()
    due = json.loads(s["data"] or "{}").get("due") if s else None
    if not due:
        raise KeyError(sid)
    due_dt = clock.utc(due)
    now = datetime.now(UTC)
    at = (
        due_dt - timedelta(days=1)
        if due_dt - now > timedelta(days=1, hours=2)
        else due_dt - timedelta(hours=2)
    )
    at = max(at, now + timedelta(minutes=5))
    with db.transaction(conn):
        actions.add_reminder(conn, s["text"], at.strftime("%Y-%m-%d %H:%M:%S"))
    return at.strftime("%Y-%m-%d %H:%M:%S")


AI_SCHEMA = {"type": "object", "required": ["suggestions"],
             "properties": {"suggestions": {"type": "array", "maxItems": 2, "items": {"type": "string"}}}}  # fmt: skip


def ask_claude(conn: sqlite3.Connection, brain, target: str, target_id: int) -> list[dict]:
    """The one Claude fallback, on the user's click: up to two things only they can do. Light model, capped."""
    if target == "draft":
        d = conn.execute("SELECT * FROM drafts WHERE id = ?", (target_id,)).fetchone()
        text = f"A draft email the user is about to send.\nTo: {d['to_name'] or ''} <{d['to_email'] or ''}>\n" \
               f"Subject: {d['subject']}\n\n{d['body']}"  # fmt: skip
    else:
        m = conn.execute("SELECT * FROM inbox WHERE id = ?", (target_id,)).fetchone()
        text = f"An email the user received from {m['from_name'] or m['from_addr']}.\nSubject: {m['subject']}\n\n{m['snippet']}"
    prompt = (f"{text}\n\nList at most two short things only the user can do well before acting on this: "
              "personal knowledge, a judgment call, a fact to check. Imperative, under 15 words each. "
              "Don't rewrite the email or restate it. An empty list is fine.")  # fmt: skip
    out = brain.ask(prompt, AI_SCHEMA, light=True, kind="suggest")
    items = [t.strip() for t in out.get("suggestions", []) if isinstance(t, str) and t.strip()][:2]
    with db.transaction(conn):
        for i, t in enumerate(items or [""], start=1):
            conn.execute(
                "INSERT INTO suggestions (target, target_id, rule, text, status) VALUES (?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (target, target_id, f"ai{i}", t[:200] or "(nothing)", "open" if t else "dismissed"),
            )
    return open_for(conn, target, target_id)
