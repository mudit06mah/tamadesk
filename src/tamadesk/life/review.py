"""Looking back, for free: a standup note, a week card and a brag doc, built from what the desk saw.

No AI: everything comes from the events, todos, focus sessions, meetings and (if `gh` is set up)
the PRs you merged. The week card is the end-of-round screen: XP, on-time finishes, focus hours per
#tag, the longest habit chain, and a title you earned this week.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, timedelta

from tamadesk.core import clock
from tamadesk.life import focus, game, github, today


def _between(d0: date, d1: date) -> tuple[str, str]:
    return today.bounds(d0)[0], today.bounds(d1)[1]


def _done(conn: sqlite3.Connection, since: str, until: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM todos WHERE status = 'done' AND done_at >= ? AND done_at < ? ORDER BY done_at",
        (since, until),
    ).fetchall()


def _shipped(since: str, until: str) -> list[dict]:
    """PRs merged in the window, from the GitHub cache only (never a slow call here)."""
    data = github.cached() or {}
    return [p for p in data.get("shipped", []) if since <= p["updated_at"].replace("T", " ")[:19] < until]


def _hours(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _bullets(rows: list[str]) -> str:
    return "\n".join(f"- {r}" for r in rows) or "- (nothing logged)"


def standup(conn: sqlite3.Connection, d: date | None = None) -> dict:
    """Yesterday (the last workday), today and blockers, as a note you can paste in a standup."""
    d = d or today.local_today()
    prev = d - timedelta(days=3 if d.weekday() == 0 else 1)  # on Monday, "yesterday" is Friday
    since, until = _between(prev, prev)
    did = [t["title"] for t in _done(conn, since, until) if t["kind"] == "todo"]
    did += [r["body"] for r in conn.execute(
        "SELECT body FROM log_entries WHERE created_at >= ? AND created_at < ?", (since, until))]  # fmt: skip
    did += [f"merged {p['repo']}#{p['number']}: {p['title']}" for p in _shipped(since, until)]
    did += [f"sent: {r['detail']}" for r in conn.execute(
        "SELECT detail FROM events WHERE kind = 'mail_sent' AND at >= ? AND at < ?", (since, until))]  # fmt: skip
    for tag, mins in focus.minutes_by_tag(conn, since, until).items():
        did.append(f"focused {_hours(mins)}" + ("" if tag == "untagged" else f" on #{tag}"))
    view = today.day(conn, d)
    plan = [f"{clock.local(e['at']).strftime('%H:%M')} {e['title']}" for e in view["timeline"]
            if e["kind"] == "meeting" and e["state"] != "cancelled"]  # fmt: skip
    plan += [e["title"] for e in view["timeline"] if e["kind"] == "todo" and e["state"] == "open"]
    plan += [e["title"] for e in view["anytime"] if not e.get("waiting")][:3]
    blocked = [e["title"] for e in view["needs_you"] if e["kind"] == "todo" and e.get("waiting")]
    blocked += [
        f"overdue: {e['title']}" for e in view["needs_you"] if e["kind"] == "todo" and not e.get("waiting")
    ]
    md = (f"**Yesterday** ({prev:%a})\n{_bullets(did)}\n\n**Today**\n{_bullets(plan)}\n\n"
          f"**Blockers**\n{_bullets(blocked) if blocked else '- none'}")  # fmt: skip
    return {"kind": "standup", "yesterday": did, "today": plan, "blockers": blocked, "markdown": md}


# the title you earned this week: first rule that fits wins
TITLES = [
    (lambda w: w["on_time"] >= 5, "Deadline Slayer", "beat 5+ deadlines"),
    (lambda w: w["focus_minutes"] >= 600, "Deep Diver", "10+ hours of focus"),
    (lambda w: w["best_chain"] >= 7, "Habit Machine", "a habit chain of 7+"),
    (lambda w: w["sent"] >= 5, "Outreach Ace", "5+ emails sent"),
    (lambda w: w["done"] >= 15, "Unstoppable", "15+ things done"),
    (lambda w: w["active_days"] >= 5, "Steady Hands", "showed up 5+ days"),
    (lambda w: w["done"] >= 1, "Getting Going", "the first wins are in"),
    (lambda w: True, "Fresh Start", "next week is yours"),
]


def week(conn: sqlite3.Connection, end: date | None = None) -> dict:
    """The week card: the last 7 days in numbers, the best moments, and the title you earned."""
    end = end or today.local_today()
    start = end - timedelta(days=6)
    since, until = _between(start, end)
    ev = conn.execute(
        "SELECT kind, xp, at, detail FROM events WHERE at >= ? AND at < ?", (since, until)
    ).fetchall()
    done = _done(conn, since, until)
    by_day = Counter(clock.local(e["at"]).date() for e in ev if e["xp"] > 0)
    per_tag = focus.minutes_by_tag(conn, since, until)
    tags = Counter(tag for t in done for tag in (t["tags"] or "").split())
    w = {
        "kind": "week",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "xp": sum(e["xp"] for e in ev),
        "done": sum(1 for t in done if t["kind"] == "todo"),
        "on_time": sum(1 for e in ev if e["kind"] == "todo_on_time"),
        "waiting_closed": sum(1 for t in done if t["kind"] == "waiting"),
        "focus_minutes": sum(per_tag.values()),
        "focus_by_tag": per_tag,
        "best_chain": max((t["chain"] for t in done), default=0),
        "sent": sum(1 for e in ev if e["kind"] == "mail_sent"),
        "moves": sum(1 for e in ev if e["kind"] in ("stage_applied", "stage_interview", "stage_replied")),
        "active_days": len(by_day),
        "best_day": max(by_day, key=by_day.get).strftime("%A") if by_day else None,
        "top_tags": [t for t, _ in tags.most_common(3)],
        "progress": game.progress(conn),
    }
    w["title"], w["title_why"] = next((t, why) for rule, t, why in TITLES if rule(w))
    w["highlights"] = [t["title"] + (f" #{t['tags'].split()[0]}" if t["tags"] else "")
                       for t in done if t["kind"] == "todo" and not t["repeat"]][-8:]  # fmt: skip
    w["highlights"] += [f"merged {p['repo']}#{p['number']}" for p in _shipped(since, until)][:4]
    focus_lines = [
        f"- #{k}: {_hours(v)}" if k != "untagged" else f"- other: {_hours(v)}" for k, v in per_tag.items()
    ]
    w["markdown"] = (
        f"## Week of {start:%d %b} · {w['title']}\n\n"
        f"+{w['xp']} XP · {w['done']} done ({w['on_time']} before the deadline) · "
        f"{_hours(w['focus_minutes'])} focused · {w['active_days']}/7 days\n\n"
        f"**Highlights**\n{_bullets(w['highlights'])}\n"
        + ("\n**Focus**\n" + "\n".join(focus_lines) + "\n" if focus_lines else "")
    )
    return w


def brag(conn: sqlite3.Connection, since_day: date, until_day: date | None = None) -> dict:
    """Everything you got done between two days, grouped by month and #tag: for reviews and resumes."""
    until_day = until_day or today.local_today()
    since, until = _between(since_day, until_day)
    groups: dict[str, dict[str, list[str]]] = {}
    for t in _done(conn, since, until):
        if t["kind"] != "todo" or t["repeat"]:
            continue
        month = clock.local(t["done_at"]).strftime("%B %Y")
        tag = (t["tags"] or "").split()[0] if t["tags"] else "other"
        groups.setdefault(month, {}).setdefault(tag, []).append(t["title"])
    for p in _shipped(since, until):
        month = clock.local(p["updated_at"].replace("T", " ")[:19]).strftime("%B %Y")
        groups.setdefault(month, {}).setdefault("shipped", []).append(
            f"{p['repo']}#{p['number']}: {p['title']}"
        )
    parts = [f"# What I got done, {since_day:%d %b %Y} to {until_day:%d %b %Y}"]
    for month, tags in groups.items():
        parts.append(f"\n## {month}")
        for tag, rows in tags.items():
            parts.append(f"\n**{'#' + tag if tag not in ('other', 'shipped') else tag}**\n{_bullets(rows)}")
    return {"kind": "brag", "groups": groups, "markdown": "\n".join(parts)}
