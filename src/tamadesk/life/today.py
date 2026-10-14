"""Today: the user's day as one ordered list, the spine every other page drills down from.

Meetings, reminders, todos due and what's already done sit on one timeline; things waiting on the
user (Up next) and undated todos sit beside it. Computed on demand from the database, like Up next,
so it can't drift. The Today page and Bolt's `my_day` tool both read this.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from tamadesk.core import clock, db
from tamadesk.life import focus, pressure, suggest, upnext

# Up next rows that can carry "only you" suggestions, and what they point at
TARGET = {"draft": "draft", "reply": "inbox", "interview": "inbox", "update": "inbox"}
# what a finished thing looks like in the "earlier today" part of the timeline
DONE_EVENTS = {
    "focus_done": "focused: {}",
    "mail_sent": "sent: {}",
    "stage_applied": "applied: {}",
    "stage_interview": "interview: {}",
    "suggestion_done": "{}",
}


def sql(dt: datetime) -> str:
    """Aware datetime -> SQLite UTC text."""
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


bounds = clock.day_bounds  # the user's day, wake to bed (see core/clock.py)
local_today = clock.today


def _entry(kind: str, key: str, title: str, *, at: str | None = None, end: str | None = None, detail: str = "",
           link: str = "", state: str = "open", ref: dict | None = None, **extra) -> dict:  # fmt: skip
    return {"kind": kind, "key": key, "title": title, "at": at, "end": end, "detail": detail, "link": link,
            "state": state, "ref": ref or {}, **extra}  # fmt: skip


def _link(row: dict) -> str:
    """Where an Up next row leads: the draft, the thread or the tab."""
    if row["kind"] in ("draft", "followup"):
        return f"mail/d{row['id']}"
    if row.get("draft_id"):
        return f"mail/d{row['draft_id']}"
    if row["kind"] == "kept":
        return f"m:{row['module']}"
    if row["kind"] == "github":
        return row["url"]
    return "mail"


def _todo(t: sqlite3.Row, **kw) -> dict:
    """A todo row with what makes it a todo: its deadline, repeat and habit chain, tags, who it waits on."""
    from tamadesk.life import repeat as repeating

    extra = {"due": t["due_at"], "repeat": repeating.label(t["repeat"]), "chain": t["chain"],
             "tags": t["tags"].split() if t["tags"] else [], "waiting": t["kind"] == "waiting", "who": t["who"]}  # fmt: skip
    kw.setdefault("state", "done" if t["status"] == "done" else "open")
    title = kw.pop("title", t["title"])
    return _entry("todo", f"t:{t['id']}", title, ref={"todo": t["id"]}, **extra | kw)


def promises_due(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Meetings that just ended and haven't been asked about: the moment to write down what you promised."""
    from tamadesk.life import calendar

    now = now or datetime.now(UTC)
    since = sql(now - timedelta(hours=3))
    done = {r[0] for r in conn.execute("SELECT cal_key FROM meeting_notes")}
    out = []
    for o in calendar.occurrences(conn, since, sql(now)):
        key = f"{o['uid']}|{o['start']}"
        if (
            o["all_day"]
            or o["status"] == "cancelled"
            or o["end"] > sql(now)
            or o["end"] < since
            or key in done
        ):
            continue
        out.append(_entry("promise", f"p:{key}", f"{o['title']} ended: anything you promised?", at=o["end"],
                          detail="each line becomes a todo", ref={"cal_key": key, "item": o["item_id"]}))  # fmt: skip
    return out


def needs_you(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """Up next, overdue todos, follow-ups on things you're waiting for, and promises from meetings
    that just ended: everything waiting on the user, most urgent first."""
    now_s = sql(now or datetime.now(UTC))
    out = promises_due(conn, now)
    for r in upnext.up_next(conn):
        key = f"n:{r['kind']}:{r['id']}:{r.get('module', '') or r.get('key', '')}"
        e = _entry("next", key, r["title"], detail=r["detail"], link=_link(r), next=r)
        if target := TARGET.get(r["kind"]):  # the things only the user can do, right on the row
            e |= {"target": target, "suggestions": suggest.open_for(conn, target, r["id"])}
            e["can_ask"] = not e["suggestions"] and not suggest.asked(conn, target, r["id"])
        out.append(e)
    for t in conn.execute(
        "SELECT * FROM todos WHERE status = 'open' AND due_at IS NOT NULL AND due_at < ? ORDER BY due_at",
        (now_s,),
    ):
        if t["kind"] == "waiting":
            title = f"Nudge {t['who']} about {t['title']}?" if t["who"] else f"Still waiting on {t['title']}?"
            out.append(_todo(t, title=title, at=t["due_at"], detail="follow-up day", state="overdue"))
        else:
            out.append(_todo(t, at=t["due_at"], detail="overdue", state="overdue"))
    return out


def timeline(conn: sqlite3.Connection, d: date, now: datetime | None = None) -> list[dict]:
    """Everything with a time on day `d`, in order: done things, meetings, reminders, todos due."""
    start, end = bounds(d)
    now_s = sql(now or datetime.now(UTC))
    q = conn.execute
    out: list[dict] = []
    for t in q("""SELECT * FROM todos WHERE due_at >= ? AND due_at < ? AND due_at >= ? AND status = 'open'
                  AND kind = 'todo'""", (start, end, now_s)):  # fmt: skip
        out.append(_todo(t, at=t["due_at"], detail="due"))
    for r in q(
        "SELECT * FROM reminders WHERE due_at >= ? AND due_at < ? AND status != 'dismissed' AND cal_key IS NULL",
        (start, end),
    ):
        out.append(_entry("reminder", f"r:{r['id']}", r["text"], at=r["due_at"], state=r["status"],
                          ref={"reminder": r["id"]}))  # fmt: skip
    for t in q("SELECT * FROM todos WHERE status = 'done' AND done_at >= ? AND done_at < ?", (start, end)):
        out.append(_todo(t, at=t["done_at"]))
    for e in q("SELECT * FROM log_entries WHERE created_at >= ? AND created_at < ?", (start, end)):
        out.append(_entry("log", f"l:{e['id']}", e["body"], at=e["created_at"], state="done",
                          tags=e["tags"].split() if e["tags"] else []))  # fmt: skip
    marks = ",".join("?" * len(DONE_EVENTS))
    still_done = {r[0] for r in q("SELECT id FROM suggestions WHERE status = 'done'")}
    for e in q(
        f"SELECT * FROM events WHERE kind IN ({marks}) AND at >= ? AND at < ?", (*DONE_EVENTS, start, end)
    ):
        tip = e["kind"] == "suggestion_done"
        if tip and e["ref_id"] not in still_done:
            continue  # undone since
        ref = {"event": e["id"]} | ({"suggestion": e["ref_id"]} if tip else {})
        out.append(_entry("did", f"e:{e['id']}", DONE_EVENTS[e["kind"]].format(e["detail"] or ""), at=e["at"],
                          state="done", ref=ref))  # fmt: skip
    out += meetings(conn, d)
    return sorted(out, key=lambda x: (x["at"] or "", x["key"]))


def meetings(conn: sqlite3.Connection, d: date) -> list[dict]:
    """Calendar occurrences on day `d` (filled in by the calendar module)."""
    from tamadesk.life import calendar

    start, end = bounds(d)
    return [
        _entry(
            "meeting",
            f"c:{o['id']}:{o['start']}",
            o["title"],
            at=o["start"],
            end=o["end"],
            detail=o["detail"],
            link=o["link"],
            state=o["status"],
            ref={"event": o["id"], "item": o["item_id"]},
            meet_url=o["meet_url"],
            all_day=o["all_day"],
        )
        for o in calendar.occurrences(conn, start, end)
    ]


def _recap_now(conn: sqlite3.Connection, r: dict) -> dict:
    """Tomorrow's picks with where they stand now: a pick finished since the recap shows done."""
    picks = []
    for x in r.get("tomorrow", []):
        x = x if isinstance(x, dict) else {"text": x, "todo_id": None}  # recaps written before ids
        row = (
            conn.execute("SELECT status FROM todos WHERE id = ?", (x["todo_id"],)).fetchone()
            if x.get("todo_id")
            else None
        )
        picks.append(x | {"status": row["status"] if row else None})
    return r | {"tomorrow": picks}


def recap(conn: sqlite3.Connection, d: date, recap_at: str) -> dict:
    """The recap as the day's last row, at bedtime: written (with its text) or still to write."""
    start, end = bounds(d)
    at = sql(clock.at_on(d, recap_at))
    row = conn.execute(
        "SELECT detail, at FROM events WHERE kind = 'recap' AND at >= ? AND at < ? ORDER BY id DESC LIMIT 1",
        (start, end),
    ).fetchone()
    if row:
        return _entry(
            "recap",
            "recap",
            "evening recap",
            at=row["at"],
            state="done",
            recap=_recap_now(conn, json.loads(row["detail"])),
        )
    return _entry("recap", "recap", "evening recap", at=at)


def day(conn: sqlite3.Connection, d: date | None = None, *, recap_at: str = "21:00",
        now: datetime | None = None) -> dict:  # fmt: skip
    """The whole day. Waiting-on-you and undated todos only make sense for today itself."""
    d = d or local_today()
    is_today = d == local_today()
    anytime = []
    if is_today:  # undated todos, things you're waiting on, and todos due on a later day (with their day)
        later, now_s = bounds(d)[1], sql(now or datetime.now(UTC))
        anytime = [_todo(t) for t in conn.execute(
            "SELECT * FROM todos WHERE status = 'open' AND due_at IS NULL AND kind = 'todo' ORDER BY id")]  # fmt: skip
        anytime += [_todo(t, at=t["due_at"], detail=f"waiting on {t['who']}" if t["who"] else "waiting")
                    for t in conn.execute("""SELECT * FROM todos WHERE status = 'open' AND kind = 'waiting'
                                             AND (due_at IS NULL OR due_at >= ?) ORDER BY due_at""", (now_s,))]  # fmt: skip
        anytime += [_todo(t, at=t["due_at"], detail="due later") for t in conn.execute(
            "SELECT * FROM todos WHERE status = 'open' AND due_at >= ? AND kind = 'todo' ORDER BY due_at", (later,))]  # fmt: skip
    rows = timeline(conn, d, now)
    if d <= local_today():  # the recap sits at its hour, not just last: later todos come after it
        rows = sorted([*rows, recap(conn, d, recap_at)], key=lambda x: (x["at"] or "", x["key"]))
    return {
        "date": d.isoformat(),
        "is_today": is_today,
        "needs_you": needs_you(conn, now) if is_today else [],
        "timeline": rows,
        "anytime": anytime,
        "progress": _done_count(conn, d),
        "focus": focus.running(conn) if is_today else None,
        # the most pressing deadline, in the user's chosen nudge style, for the companion's line
        "pressure": pressure.most_pressing(
            conn, pressure.tone(db.get_profile(conn, "about", {}).get("nudge")), now
        )
        if is_today
        else None,
    }


def _done_count(conn: sqlite3.Connection, d: date) -> int:
    start, end = bounds(d)
    return conn.execute(
        "SELECT count(*) FROM todos WHERE status = 'done' AND done_at >= ? AND done_at < ?", (start, end)
    ).fetchone()[0]


def brief(conn: sqlite3.Connection, d: date | None = None, recap_at: str = "21:00") -> dict:
    """A compact version for Bolt: local times, no UI fields."""
    full = day(conn, d, recap_at=recap_at)

    def local(ts: str | None) -> str | None:
        """Just the time on the day itself; a full date otherwise, so 'Fri' is never read as last Friday."""
        if not ts:
            return None
        dt = clock.local(ts)
        return dt.strftime("%H:%M" if dt.date().isoformat() == full["date"] else "%a %d %b %H:%M")

    def slim(e: dict) -> dict:
        out = {"what": e["kind"], "title": e["title"], "at": local(e["at"]), "detail": e["detail"] or None,
               "state": e["state"] if e["state"] != "open" else None}  # fmt: skip
        if e["kind"] == "meeting":
            out |= {"until": local(e["end"]), "join": e.get("meet_url")}
        if e.get("suggestions"):
            out["only_you"] = [s["text"] for s in e["suggestions"]]
        return {k: v for k, v in out.items() if v}

    return {
        "date": f"{full['date']} ({date.fromisoformat(full['date']):%A})",
        **{k: [slim(e) for e in full[k]] for k in ("needs_you", "timeline", "anytime")},
    }
