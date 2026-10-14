"""Calendar: the user's meetings, from invites in their mail and an optional private iCal feed.

Zero tokens: .ics files are parsed directly. Only event fields are stored (title, times, meeting
link, organizer, recurrence), never the mail body, the description or the attendee list. Both
sources merge on the iCal UID (plus RECURRENCE-ID for a single changed occurrence); the higher
SEQUENCE wins and the feed wins ties, since it's the calendar's own copy. Recurring events are
expanded when read (recurring-ical-events), so nothing stored can go stale.

The feed URL is a secret: it lives in <home>/secrets.json and never appears in the API, logs or
error messages.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta

import recurring_ical_events
import x_wr_timezone
from icalendar import Calendar, Event

from tamadesk.core import clock, db
from tamadesk.core.config import Settings
from tamadesk.core.net import NetError, fetch
from tamadesk.life import inbox, mail, pipeline

log = logging.getLogger("tamadesk")

FEED_SECRET = "calendar_feed"
WINDOW_DAYS = (1, 60)  # what the feed keeps: from yesterday to two months ahead
# only these properties survive into storage; DESCRIPTION, ATTENDEE, ATTACH and the rest are dropped
KEEP = ("UID", "DTSTART", "DTEND", "DURATION", "RRULE", "RDATE", "EXDATE", "RECURRENCE-ID", "SEQUENCE", "STATUS",
        "SUMMARY", "LOCATION", "DTSTAMP")  # fmt: skip
MEET = re.compile(
    r"https://(?:meet\.google\.com/[a-z0-9-]+|[\w.-]*zoom\.us/[jw]/[\w?=&.-]+|teams\.(?:microsoft|live)\.com/[^\s<>\"]+"
    r"|whereby\.com/[\w-]+|[\w.-]*webex\.com/[^\s<>\"]+)",
    re.IGNORECASE,
)
FREE_MAIL = {"gmail", "googlemail", "outlook", "hotmail", "live", "yahoo", "icloud", "proton", "protonmail"}


# ---------------------------------------------------------------- parsing


def _utc(v: date | datetime) -> str:
    """An iCal date or datetime -> SQLite UTC text. Dates and floating times are the user's local time."""
    if not isinstance(v, datetime):
        v = datetime.combine(v, time())
    if v.tzinfo is None:
        v = v.astimezone()
    return v.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _addr(v) -> str:
    return str(v or "").removeprefix("mailto:").removeprefix("MAILTO:").strip().lower()


def _meet_url(ev: Event) -> str | None:
    for key in ("X-GOOGLE-CONFERENCE", "URL", "LOCATION", "DESCRIPTION"):
        if (m := MEET.search(str(ev.get(key) or ""))) is not None:
            return m.group(0).rstrip(".,)")
    return None


def _clean(ev: Event) -> Event:
    out = Event()
    for key in KEEP:
        for v in ev.get(key) if isinstance(ev.get(key), list) else [ev.get(key)]:
            if v is not None:
                out.add(key, v) if key in ("RDATE", "EXDATE") else out.__setitem__(key, v)
    return out


def _tz_blocks(cal: Calendar, ev: Event) -> str:
    """The VTIMEZONE definitions an event refers to (Outlook's 'Pacific Standard Time' needs them)."""
    raw = ev.to_ical().decode()
    return "".join(
        tz.to_ical().decode()
        for tz in cal.walk("VTIMEZONE")
        if f"TZID={tz.get('TZID')}" in raw.replace('"', "")
    )


def parse(data: bytes | str) -> tuple[str, list[dict]]:
    """An .ics file -> (METHOD, events). Each event has only the fields tamadesk keeps."""
    cal = x_wr_timezone.to_standard(Calendar.from_ical(data))
    method = str(cal.get("METHOD") or "PUBLISH").upper()
    out = []
    for ev in cal.walk("VEVENT"):
        if not ev.get("UID") or not ev.get("DTSTART"):
            continue
        start = ev.decoded("DTSTART")
        if ev.get("DTEND"):
            end = ev.decoded("DTEND")
        elif ev.get("DURATION"):
            end = start + ev.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if not isinstance(start, datetime) else timedelta())
        rid = ev.get("RECURRENCE-ID")
        org = ev.get("ORGANIZER")
        out.append(
            {
                "uid": str(ev["UID"]),
                "recurrence_id": _utc(rid.dt) if rid is not None else "",
                "sequence": int(ev.get("SEQUENCE") or 0),
                "status": "cancelled" if method == "CANCEL" else _status(ev),
                "title": str(ev.get("SUMMARY") or "(no title)")[:200],
                "start_at": _utc(start),
                "end_at": _utc(end),
                "all_day": int(not isinstance(start, datetime)),
                "recurring": int(bool(ev.get("RRULE") or ev.get("RDATE"))),
                "meet_url": _meet_url(ev),
                "location": str(ev.get("LOCATION") or "")[:200] or None,
                "organizer_name": str(org.params.get("CN", "")) if org is not None else "",
                "organizer_email": _addr(org),
                "attendees": _attendees(ev),
                "until": _until(ev),
                "vevent": _clean(ev).to_ical().decode(),
                "tz": _tz_blocks(cal, ev),
            }
        )
    return method, out


def _status(ev: Event) -> str:
    status = str(ev.get("STATUS") or "").lower()
    return status if status in ("tentative", "cancelled") else "confirmed"


def _attendees(ev: Event) -> set[str]:
    a = ev.get("ATTENDEE")
    return {_addr(x) for x in (a if isinstance(a, list) else [a]) if x}


def _until(ev: Event) -> str | None:
    rule = ev.get("RRULE")
    if not rule or not rule.get("UNTIL"):
        return None
    return _utc(rule["UNTIL"][0])


# ---------------------------------------------------------------- storing


def _item_for(conn: sqlite3.Connection, ev: dict) -> int | None:
    """The job or lead an event is about: the organizer's company or its name in the title."""
    domain = ev["organizer_email"].split("@")[-1] if "@" in ev["organizer_email"] else ""
    stem = inbox._stem(domain) if domain else ""
    title = ev["title"].lower()
    for item_id, keys in inbox.pipeline_keys(conn):
        if (stem and stem not in FREE_MAIL and stem in keys) or any(
            re.search(rf"\b{re.escape(k)}\b", title) for k in keys
        ):
            return item_id
    return None


def upsert(conn: sqlite3.Connection, ev: dict, source: str) -> int | None:
    """Store one event (or one changed occurrence). Returns its row id, or None if it was older news."""
    cur = conn.execute(
        "SELECT * FROM cal_events WHERE uid = ? AND recurrence_id = ?", (ev["uid"], ev["recurrence_id"])
    )
    row = cur.fetchone()
    tag = f",{source},"
    if row is not None:
        sources = row["sources"] if tag in row["sources"] else row["sources"] + tag.lstrip(",")
        older = ev["sequence"] < row["sequence"]
        tie_lost = ev["sequence"] == row["sequence"] and source == "mail" and ",feed," in row["sources"]
        same = (ev["vevent"], ev["status"], ev["tz"]) == (row["vevent"], row["status"], row["tz"])
        if older or same or (tie_lost and row["status"] != "gone"):
            conn.execute("UPDATE cal_events SET sources = ? WHERE id = ?", (sources, row["id"]))
            return None
    else:
        sources = tag
    fields = {k: ev[k] for k in ("sequence", "status", "title", "start_at", "end_at", "all_day", "recurring",
                                 "meet_url", "location", "organizer_name", "organizer_email", "vevent", "tz")}  # fmt: skip
    fields |= {"sources": sources, "until": ev["until"]}
    with db.transaction(conn):
        if row is None:
            item_id = _item_for(conn, ev)
            cols = ["uid", "recurrence_id", "item_id", *fields]
            rid = conn.execute(
                f"INSERT INTO cal_events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (ev["uid"], ev["recurrence_id"], item_id, *fields.values()),
            ).lastrowid
        else:
            rid, item_id = row["id"], row["item_id"]
            conn.execute(
                f"UPDATE cal_events SET {', '.join(f'{k} = ?' for k in fields)}, updated_at = datetime('now') WHERE id = ?",
                (*fields.values(), rid),
            )
        # alerts are made just in time; a moved or cancelled meeting must not ring at the old time
        conn.execute("DELETE FROM reminders WHERE status = 'pending' AND cal_key LIKE ?", (f"{ev['uid']}|%",))
        if item_id and ev["status"] != "cancelled" and row is None:
            who = ev["organizer_name"] or ev["organizer_email"] or "the calendar"
            pipeline.set_stage(conn, item_id, "interview", why=f"calendar invite from {who}")
    return rid


def add_local(conn: sqlite3.Connection, title: str, start_utc: datetime, minutes: int = 30) -> int:
    """A meeting typed into the desk ("meeting design review at 3pm"): no calendar needed. It rings
    and shows on Today like an invite would."""
    import uuid

    ev = Event()
    ev.add("UID", f"local-{uuid.uuid4().hex}@tamadesk")
    ev.add("DTSTART", start_utc.replace(tzinfo=UTC))
    ev.add("DTEND", start_utc.replace(tzinfo=UTC) + timedelta(minutes=minutes))
    ev.add("SUMMARY", title)
    ev.add("DTSTAMP", datetime.now(UTC))
    cal = Calendar()
    cal.add_component(ev)
    _, [parsed] = parse(cal.to_ical())
    return upsert(conn, parsed, "local")


def from_mail(s: Settings, conn: sqlite3.Connection, msg) -> int:
    """Store the calendar invite in a message, if it has one and it's addressed to the user.
    This is the one exception to "only mail about something you started": only event fields are kept."""
    if not s.calendar.from_mail:
        return 0
    me = s.mail.address.lower()
    n = 0
    for part in msg.walk():
        if part.get_content_type() not in ("text/calendar", "application/ics") and not (
            part.get_filename() or ""
        ).lower().endswith(".ics"):
            continue
        try:
            method, events = parse(part.get_payload(decode=True) or b"")
        except ValueError:
            continue
        if method == "REPLY":  # someone answering an invite you sent
            continue
        for ev in events:
            if me and (me in ev["attendees"] or me == ev["organizer_email"]):
                n += upsert(conn, ev, "mail") is not None
    return n


def _in_window(ev: dict, lo: str, hi: str) -> bool:
    if ev["recurring"] and not ev["recurrence_id"]:
        return ev["until"] is None or ev["until"] >= lo
    return ev["end_at"] >= lo and ev["start_at"] < hi


def sync_feed(s: Settings, conn: sqlite3.Connection, *, get=fetch) -> int:
    """Read the private iCal feed once. Events that vanished from it are marked gone."""
    url = mail.get_secret(s, FEED_SECRET)
    if not url:
        return 0
    now = datetime.now(UTC)
    lo, hi = (_utc(now - timedelta(days=WINDOW_DAYS[0])), _utc(now + timedelta(days=WINDOW_DAYS[1])))
    try:
        _, events = parse(get(re.sub(r"^webcal://", "https://", url), timeout=30))
    except (NetError, ValueError) as e:
        # never log the URL: it is the password to the calendar
        msg = (
            "couldn't reach the calendar feed"
            if isinstance(e, NetError)
            else "the calendar feed isn't valid iCal"
        )
        db.set_profile(conn, "calendar_feed_error", msg)
        log.warning("calendar feed failed: %s", type(e).__name__)
        return 0
    seen, n = set(), 0
    for ev in events:
        if _in_window(ev, lo, hi):
            seen.add((ev["uid"], ev["recurrence_id"]))
            n += upsert(conn, ev, "feed") is not None
    for r in conn.execute("SELECT id, uid, recurrence_id, start_at, end_at, recurring, until FROM cal_events "
                          "WHERE sources LIKE '%,feed,%' AND status != 'gone'").fetchall():  # fmt: skip
        if (r["uid"], r["recurrence_id"]) not in seen and _in_window(dict(r), lo, hi):
            conn.execute(
                "UPDATE cal_events SET status = 'gone', updated_at = datetime('now') WHERE id = ?", (r["id"],)
            )
            conn.execute(
                "DELETE FROM reminders WHERE status = 'pending' AND cal_key LIKE ?", (f"{r['uid']}|%",)
            )
    db.set_profile(conn, "calendar_feed_error", None)
    db.set_profile(conn, "calendar_synced", _utc(now))
    return n


# ---------------------------------------------------------------- deadline feeds

DEADLINE_SECRET = "deadline_feeds"  # [{url, tag}]: school (Canvas, Moodle), a team's release calendar…


def deadline_feeds(s: Settings) -> list[dict]:
    """The calendar feeds whose events become todos with deadlines ([{url, tag}]), kept with the secrets."""
    feeds = mail.get_secret(s, DEADLINE_SECRET)
    return feeds if isinstance(feeds, list) else []


def _deadlines(data: bytes, now: datetime) -> list[tuple[str, str, str]]:
    """(key, title, due UTC) for every event or task in a feed due in the next four months.
    An all-day event is due at the end of that day."""
    cal = x_wr_timezone.to_standard(Calendar.from_ical(data))
    out = []

    def due_of(v: date | datetime) -> str:
        if not isinstance(v, datetime):
            v = datetime.combine(v, time(23, 59))
        return _utc(v)

    for o in recurring_ical_events.of(cal).between(now - timedelta(days=1), now + timedelta(days=120)):
        if str(o.get("STATUS") or "").upper() != "CANCELLED":
            start = o.decoded("DTSTART")
            out.append(
                (f"{o['UID']}|{_utc(start)}", str(o.get("SUMMARY") or "(no title)")[:200], due_of(start))
            )
    for td in cal.walk("VTODO"):  # some school systems publish assignments as tasks with a DUE date
        if td.get("DUE") and str(td.get("STATUS") or "").upper() not in ("COMPLETED", "CANCELLED"):
            out.append(
                (f"{td['UID']}|task", str(td.get("SUMMARY") or "(no title)")[:200], due_of(td.decoded("DUE")))
            )
    return out


def sync_deadlines(s: Settings, conn: sqlite3.Connection, *, get=fetch) -> int:
    """Turn each deadline feed into todos (tagged with the feed's name). A moved deadline moves the
    todo; one that left the feed is dropped quietly. Returns how many todos are new."""
    from tamadesk.life import actions

    now = datetime.now(UTC)
    now_s = _utc(now)
    added = 0
    for f in deadline_feeds(s):
        tag = re.sub(r"[^\w-]", "", f.get("tag", "")).lower() or "deadline"
        try:
            items = _deadlines(get(re.sub(r"^webcal://", "https://", f["url"]), timeout=30), now)
        except (NetError, ValueError, KeyError):
            log.warning("a deadline feed failed")  # never log the URL
            continue
        seen = set()
        for key, title, due in items:
            ext = f"{tag}|{key}"[:300]
            seen.add(ext)
            row = conn.execute("SELECT * FROM todos WHERE ext_uid = ?", (ext,)).fetchone()
            if row is None and due >= now_s:
                with db.transaction(conn):
                    actions.add_todo(conn, title, due, tags=tag, ext_uid=ext)
                added += 1
            elif (
                row is not None and row["status"] == "open" and (row["due_at"], row["title"]) != (due, title)
            ):
                conn.execute(
                    "UPDATE todos SET due_at = ?, title = ?, nudged = 0 WHERE id = ?", (due, title, row["id"])
                )
        for r in conn.execute("SELECT id, ext_uid FROM todos WHERE ext_uid LIKE ? AND status = 'open' AND due_at >= ?",
                              (f"{tag}|%", now_s)).fetchall():  # fmt: skip
            if r["ext_uid"] not in seen:
                conn.execute("UPDATE todos SET status = 'dropped' WHERE id = ?", (r["id"],))
    return added


# ---------------------------------------------------------------- reading


def _calendar(rows: list[sqlite3.Row]) -> Calendar:
    text = "".join(dict.fromkeys(r["tz"] for r in rows if r["tz"])) + "".join(r["vevent"] for r in rows)
    return Calendar.from_ical(
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//tamadesk//EN\r\n{text}END:VCALENDAR\r\n"
    )


def occurrences(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Every meeting overlapping [start, end) (SQLite UTC text), recurring ones expanded, in order."""
    rows = conn.execute(
        "SELECT * FROM cal_events WHERE status != 'gone' AND ((recurring = 1 AND recurrence_id = '') "
        "OR (end_at > ? AND start_at < ?) OR recurrence_id != '')",
        (start, end),
    ).fetchall()
    by_uid: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_uid.setdefault(r["uid"], []).append(r)
    lo = clock.utc(start)
    hi = clock.utc(end)
    items = {r["id"]: r["item_id"] for r in conn.execute("SELECT id, item_id FROM cal_events")}
    modules = {r["id"]: r["module"] for r in conn.execute("SELECT id, module FROM items WHERE id IN "
                                                          "(SELECT item_id FROM cal_events WHERE item_id IS NOT NULL)")}  # fmt: skip
    out = []
    for uid, group in by_uid.items():
        master = next((r for r in group if not r["recurrence_id"]), group[0])
        overrides = {r["recurrence_id"]: r for r in group if r["recurrence_id"]}
        try:
            occ = recurring_ical_events.of(_calendar(group)).between(lo, hi)
        except Exception:  # noqa: BLE001 - one broken event must not hide the rest of the day
            log.warning("couldn't expand calendar event %s", uid)
            continue
        for o in occ:
            s0 = o.decoded("DTSTART")
            e0 = o.decoded("DTEND") if o.get("DTEND") else s0
            rid = o.get("RECURRENCE-ID")
            row = overrides.get(_utc(rid.dt)) if rid is not None else None
            row = row or master
            status = "cancelled" if (master["status"] == "cancelled" or row["status"] == "cancelled"
                                     or str(o.get("STATUS") or "").upper() == "CANCELLED") else row["status"]  # fmt: skip
            item_id = items.get(master["id"])
            who = row["organizer_name"] or row["organizer_email"]
            out.append({
                "id": master["id"], "uid": uid, "start": _utc(s0), "end": _utc(e0), "title": str(o.get("SUMMARY") or row["title"]),
                "status": status, "all_day": bool(row["all_day"]), "meet_url": row["meet_url"], "item_id": item_id,
                "detail": " · ".join(x for x in (who, row["location"] if not row["meet_url"] else "") if x),
                "link": f"m:{modules[item_id]}/i{item_id}" if item_id in modules else "",
            })  # fmt: skip
    return sorted(out, key=lambda x: (not x["all_day"], x["start"]))


def alerts(s: Settings, conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Turn meetings starting soon into reminders, so the usual ring, dialog and notification happen.
    One per occurrence (cal_key), made just in time, so a moved meeting rings at its new time."""
    now = now or datetime.now(UTC)
    lead = timedelta(minutes=s.calendar.remind_min)
    n = 0
    for o in occurrences(conn, _utc(now), _utc(now + lead + timedelta(minutes=1))):
        if o["all_day"] or o["status"] == "cancelled" or o["start"] < _utc(now):
            continue
        due = clock.utc(o["start"]) - lead
        mins = s.calendar.remind_min
        n += conn.execute(
            "INSERT INTO reminders (text, due_at, cal_key) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (f"{o['title']} in {mins} min" if mins else o["title"], _utc(due), f"{o['uid']}|{o['start']}"),
        ).rowcount
    return n


def status(s: Settings, conn: sqlite3.Connection) -> dict:
    """For Settings: never the URL itself, only whether one is set."""
    return {
        "feed_set": bool(mail.get_secret(s, FEED_SECRET)),
        "from_mail": s.calendar.from_mail,
        "remind_min": s.calendar.remind_min,
        "synced": db.get_profile(conn, "calendar_synced"),
        "error": db.get_profile(conn, "calendar_feed_error"),
        "events": conn.execute("SELECT count(*) FROM cal_events WHERE status != 'gone'").fetchone()[0],
        # each deadline feed by its name and host only: the full address is a secret
        "deadline_feeds": [
            {"tag": f.get("tag", ""), "host": re.sub(r"^\w+://([^/]+).*", r"\1", f.get("url", ""))}
            for f in deadline_feeds(s)
        ],
    }
