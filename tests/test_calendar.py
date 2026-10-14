"""Calendar: invites in mail and a private feed, merged on UID, with updates, cancellations,
recurrence and timezones right. All fixtures are made up (example.com)."""

import logging
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest

from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import calendar, inbox, mail, today

ME = "me@example.com"
NY = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
"""


def ics(body: str, method: str = "REQUEST", tz: str = NY) -> str:
    text = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//test//EN\nMETHOD:{method}\n{tz}{body}END:VCALENDAR\n"
    return text.replace("\n", "\r\n")


def vevent(uid="call-1@example.com", start="20261015T100000", end="20261015T103000", seq=0, extra="",
           summary="Design chat with Riley") -> str:  # fmt: skip
    return f"""BEGIN:VEVENT
UID:{uid}
SEQUENCE:{seq}
DTSTAMP:20261007T120000Z
DTSTART;TZID=America/New_York:{start}
DTEND;TZID=America/New_York:{end}
SUMMARY:{summary}
DESCRIPTION:Private agenda: salary numbers. Join https://meet.google.com/abc-defg-hij
ORGANIZER;CN=Riley:mailto:riley@contoso.example
ATTENDEE;CN=Me:mailto:{ME}
ATTENDEE;CN=Someone Else:mailto:other@contoso.example
{extra}END:VEVENT
"""


@pytest.fixture
def conn(client):
    s = get_settings()
    s.mail.address = ME
    c = db.connect(s.db_path)
    yield c
    c.close()


def store(conn, text: str, source: str = "mail") -> None:
    _, events = calendar.parse(text)
    for ev in events:
        calendar.upsert(conn, ev, source)


def day_of(conn, start: str, end: str) -> list[dict]:
    return calendar.occurrences(conn, start, end)


def test_an_invite_keeps_only_event_fields(conn):
    store(conn, ics(vevent()))
    [o] = day_of(conn, "2026-10-15 00:00:00", "2026-10-16 00:00:00")
    assert (o["title"], o["start"], o["end"]) == (
        "Design chat with Riley",
        "2026-10-15 14:00:00",
        "2026-10-15 14:30:00",
    )
    assert o["meet_url"] == "https://meet.google.com/abc-defg-hij"
    row = dict(conn.execute("SELECT * FROM cal_events").fetchone())
    stored = " ".join(str(v) for v in row.values())
    assert "salary" not in stored and "other@contoso.example" not in stored and "ATTENDEE" not in stored


def test_updates_and_cancellations_follow_the_sequence(conn):
    store(conn, ics(vevent()))
    store(conn, ics(vevent(seq=1, start="20261015T150000", end="20261015T153000")))
    store(conn, ics(vevent(seq=0)))  # a late copy of the original invite changes nothing
    [o] = day_of(conn, "2026-10-15 00:00:00", "2026-10-16 00:00:00")
    assert o["start"] == "2026-10-15 19:00:00"
    store(conn, ics(vevent(seq=2, start="20261015T150000", end="20261015T153000"), method="CANCEL"))
    [o] = day_of(conn, "2026-10-15 00:00:00", "2026-10-16 00:00:00")
    assert o["status"] == "cancelled"


def test_outlook_windows_timezone_names(conn):
    pst = (
        NY.replace("America/New_York", "Pacific Standard Time")
        .replace("-0500", "-0800")
        .replace("-0400", "-0700")
    )
    ev = vevent().replace("America/New_York", "Pacific Standard Time")
    store(conn, ics(ev, tz=pst))
    [o] = day_of(conn, "2026-10-15 00:00:00", "2026-10-16 00:00:00")
    assert o["start"] == "2026-10-15 17:00:00"  # 10:00 PDT


def test_weekly_series_with_exdate_moved_and_cancelled_occurrences(conn):
    weekly = "RRULE:FREQ=WEEKLY;COUNT=6\nEXDATE;TZID=America/New_York:20261012T090000\n"
    store(
        conn,
        ics(vevent(uid="sync@example.com", start="20261005T090000", end="20261005T093000", extra=weekly)),
    )
    moved = vevent(uid="sync@example.com", start="20261020T110000", end="20261020T113000", seq=1,
                   extra="RECURRENCE-ID;TZID=America/New_York:20261019T090000\n")  # fmt: skip
    store(conn, ics(moved))
    gone = vevent(uid="sync@example.com", start="20261026T090000", end="20261026T093000", seq=1,
                  extra="RECURRENCE-ID;TZID=America/New_York:20261026T090000\n")  # fmt: skip
    store(conn, ics(gone, method="CANCEL"))
    occ = day_of(conn, "2026-10-01 00:00:00", "2026-11-30 00:00:00")
    got = [(o["start"], o["status"]) for o in occ]
    assert got == [
        ("2026-10-05 13:00:00", "confirmed"),
        # 12 Oct: excluded
        ("2026-10-20 15:00:00", "confirmed"),  # moved from Mon 19 to Tue 20, 11:00
        ("2026-10-26 13:00:00", "cancelled"),
        ("2026-11-02 14:00:00", "confirmed"),  # after the clocks change: still 09:00 in New York
        ("2026-11-09 14:00:00", "confirmed"),
    ]


def test_all_day_events_come_first(conn):
    allday = """BEGIN:VEVENT
UID:offsite@example.com
DTSTAMP:20261007T120000Z
DTSTART;VALUE=DATE:20261015
DTEND;VALUE=DATE:20261016
SUMMARY:Team offsite
ATTENDEE:mailto:me@example.com
END:VEVENT
"""
    store(conn, ics(vevent() + allday))
    s, e = today.bounds(datetime(2026, 10, 15).date())
    occ = day_of(conn, s, e)
    assert [o["title"] for o in occ] == ["Team offsite", "Design chat with Riley"] and occ[0]["all_day"]


def test_mail_and_feed_merge_on_uid(conn):
    store(conn, ics(vevent()), "mail")
    store(conn, ics(vevent(summary="Design chat (feed copy)"), method="PUBLISH"), "feed")
    store(conn, ics(vevent(summary="older mail copy")), "mail")  # same sequence: the feed wins ties
    rows = conn.execute("SELECT sources, title FROM cal_events").fetchall()
    assert [tuple(r) for r in rows] == [(",mail,feed,", "Design chat (feed copy)")]


def test_an_event_that_leaves_the_feed_is_gone(conn):
    s = get_settings()
    mail.set_secret(s, calendar.FEED_SECRET, "https://calendar.example/private-SECRET123/basic.ics")
    soon = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y%m%dT%H%M00")
    later = (datetime.now(UTC) + timedelta(days=2, minutes=30)).strftime("%Y%m%dT%H%M00")
    feed = ics(vevent(start=soon, end=later) + vevent(uid="b@example.com", start=soon, end=later), "PUBLISH")
    assert calendar.sync_feed(s, conn, get=lambda url, **kw: feed.encode()) == 2
    one = ics(vevent(uid="b@example.com", start=soon, end=later), "PUBLISH")
    calendar.sync_feed(s, conn, get=lambda url, **kw: one.encode())
    rows = dict(conn.execute("SELECT uid, status FROM cal_events").fetchall())
    assert rows == {"call-1@example.com": "gone", "b@example.com": "confirmed"}


def test_the_feed_url_never_leaks(client, conn, caplog):
    s = get_settings()
    client.put("/api/calendar", json={"feed": "webcal://calendar.example/private-SECRET123/basic.ics"})
    assert mail.get_secret(s, calendar.FEED_SECRET).startswith("webcal://")
    body = client.get("/api/calendar").text
    assert "SECRET123" not in body and '"feed_set":true' in body

    def broken(url, **kw):
        raise calendar.NetError(f"calendar.example: {url} 404")

    with caplog.at_level(logging.DEBUG):
        calendar.sync_feed(s, conn, get=broken)
    assert "SECRET123" not in caplog.text and "SECRET123" not in client.get("/api/calendar").text
    assert client.get("/api/calendar").json()["error"]


def test_invites_in_mail_are_read_only_when_addressed_to_me(conn):
    s = get_settings()

    def msg(to_me: bool) -> EmailMessage:
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "riley@contoso.example", "Invitation", f"<{to_me}@x>"
        m.set_content("You're invited. Private body text.")
        ev = vevent() if to_me else vevent(uid="x@example.com").replace(ME, "someone@example.com")
        m.add_attachment(ics(ev).encode(), maintype="text", subtype="calendar", filename="invite.ics")
        return m

    assert calendar.from_mail(s, conn, msg(False)) == 0
    assert calendar.from_mail(s, conn, msg(True)) == 1
    assert calendar.from_mail(s, conn, msg(True)) == 0  # re-reading it changes nothing
    assert conn.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0  # the mail itself isn't stored
    s.calendar.from_mail = False
    try:
        assert calendar.from_mail(s, conn, msg(True)) == 0
    finally:
        s.calendar.from_mail = True


def test_an_invite_from_a_pipeline_company_moves_it_to_interview(conn):
    job = conn.execute(
        "INSERT INTO items (module, ext_id, source, title, url, data, status) VALUES "
        "('jobs', 'c', 'x', 'UI Designer, Contoso', 'https://contoso.example/jobs/1', "
        "'{\"apply_url\": \"https://contoso.example/jobs/1/apply\"}', 'saved')"
    ).lastrowid
    store(conn, ics(vevent()))
    assert conn.execute("SELECT stage FROM items WHERE id = ?", (job,)).fetchone()[0] == "interview"
    [o] = day_of(conn, "2026-10-15 00:00:00", "2026-10-16 00:00:00")
    assert o["item_id"] == job and o["link"] == f"m:jobs/i{job}"
    assert inbox.pipeline_keys(conn)  # the same matching the inbox uses


def test_alerts_ring_once_follow_moves_and_give_no_xp(client, conn):
    s = get_settings()
    now = datetime(2026, 10, 15, 13, 52, tzinfo=UTC)  # 8 minutes before 10:00 New York
    store(conn, ics(vevent()))
    assert calendar.alerts(s, conn, now) == 1
    assert calendar.alerts(s, conn, now) == 0
    rid, due = conn.execute("SELECT id, due_at FROM reminders").fetchone()
    assert due == "2026-10-15 13:50:00"
    store(conn, ics(vevent(seq=1, start="20261015T110000", end="20261015T113000")))  # moved an hour later
    assert conn.execute("SELECT count(*) FROM reminders").fetchone()[0] == 0
    assert calendar.alerts(s, conn, now) == 0  # not within 10 minutes any more
    assert calendar.alerts(s, conn, now + timedelta(hours=1)) == 1
    conn.execute("UPDATE reminders SET status = 'fired'")
    rid = conn.execute("SELECT id FROM reminders").fetchone()[0]
    assert client.post(f"/api/reminders/{rid}/dismiss").json()["xp"] == 0
