"""Today: one ordered list for the day, built from todos, reminders, meetings, Up next and what got done."""

from datetime import date, datetime, timedelta

from tamadesk.assistant import tools
from tamadesk.core import clock
from tamadesk.core.config import get_settings
from tamadesk.life import actions, today


def ts(dt: datetime) -> str:
    return clock.sql_ts(clock.to_utc(dt))


def test_the_day_is_one_ordered_list(client, conn):
    d = clock.today()  # the user's day: it starts mid-night, not at midnight (core/clock.py)

    def at(hm: str, days: int = 0):
        return clock.at_on(d + timedelta(days=days), hm)

    start = clock.local(clock.day_bounds(d)[0])
    now = start + timedelta(minutes=30)  # pinned, so this never flakes near the turnover
    later = actions.add_todo(conn, "ship the deck", ts(at("23:00")))
    actions.add_reminder(conn, "stretch", ts(at("22:00")))
    undated = actions.add_todo(conn, "book dentist")
    overdue = actions.add_todo(conn, "pay invoice", ts(start - timedelta(days=2)))
    tomorrow = actions.add_todo(conn, "call the bank", ts(at("09:00", days=1)))
    done = actions.add_todo(conn, "water plants")
    actions.complete_todo(conn, done)
    conn.execute("UPDATE todos SET done_at = ? WHERE id = ?", (ts(start + timedelta(minutes=10)), done))
    conn.execute("INSERT INTO reminders (text, due_at, cal_key) VALUES ('Standup in 10 min', ?, 'u|x')",
                 (ts(at("09:00")),))  # fmt: skip

    v = today.day(conn, d, now=now, recap_at="21:00")
    keys = [e["key"] for e in v["timeline"]]
    assert keys.index(f"t:{done}") < keys.index(f"t:{later}")
    assert keys.index("recap") < keys.index(f"t:{later}")  # 21:00 recap before a 23:00 deadline
    assert [e["title"] for e in v["timeline"] if e["kind"] == "reminder"] == [
        "stretch"
    ]  # meeting alerts aren't rows
    assert f"t:{overdue}" in [e["key"] for e in v["needs_you"]]
    assert [e["key"] for e in v["anytime"]] == [f"t:{undated}", f"t:{tomorrow}"]
    assert v["progress"] == 1 and v["is_today"]

    other = client.get(f"/api/today?day={(d + timedelta(days=1)).isoformat()}").json()
    assert (
        other["needs_you"] == []
        and other["anytime"] == []
        and "recap" not in [e["key"] for e in other["timeline"]]
    )
    assert client.get("/api/today?day=nope").status_code == 400


def test_each_draft_waiting_is_its_own_row_linked_to_it(client, conn):
    a = actions.add_draft(
        conn, ask="t", subject="Hello", body="b", to_name="Alex", to_email="alex@example.com"
    )
    rows = client.get("/api/today").json()["needs_you"]
    [r] = [r for r in rows if r["kind"] == "next"]
    assert (r["title"], r["link"]) == ("Draft to Alex", f"mail/d{a}")


def test_bolt_answers_whats_my_day_with_one_tool(conn):
    actions.add_todo(conn, "book dentist")
    out = tools.my_day(get_settings(), conn)
    assert out["anytime"] == [{"what": "todo", "title": "book dentist"}]
    assert tools.my_day(get_settings(), conn, "tomorrow-ish") == "day must be YYYY-MM-DD"


def test_a_night_owls_day_runs_from_waking_to_bed(client, conn):
    """Bed at 1am, up at 9: the day turns over at 5am, 12:30am is still today, and the recap is at 1am."""
    s = get_settings()
    assert client.put("/api/settings", json={"wake": "09:00", "bed": "01:00"}).json() == {"ok": True}
    assert (s.day.wake, s.day.bed_at, clock.turn_minutes()) == ("09:00", "01:00", 300)
    late = datetime(2026, 10, 15, 0, 30).astimezone()  # 12:30am on the 15th
    assert clock.today(late) == date(2026, 10, 14)  # hasn't slept yet: still the 14th
    assert clock.today(late.replace(hour=6)) == date(2026, 10, 15)  # up early: the new day
    assert clock.at_on(date(2026, 10, 14), "01:00").day == 15  # the 14th's recap is at 1am on the 15th
    assert clock.day_bounds(date(2026, 10, 14))[0] == ts(datetime(2026, 10, 14, 5, 0).astimezone())

    d = clock.today()
    late_todo = actions.add_todo(conn, "late-night commit")
    actions.complete_todo(conn, late_todo)
    one_am = clock.at_on(d, "00:30")  # after midnight, before bed: still today
    conn.execute("UPDATE todos SET done_at = ? WHERE id = ?", (ts(one_am), late_todo))
    keys = [e["key"] for e in today.day(conn, d, recap_at=s.day.bed_at)["timeline"]]
    assert keys.index(f"t:{late_todo}") < keys.index("recap") == len(keys) - 1  # the recap closes the day
    assert client.get("/api/state").json()["day"] | {"today": None} == {
        "wake": "09:00", "bed": "01:00", "today": None, "todo_goal": 3, "quiet_start": None, "quiet_end": None}  # fmt: skip


def test_new_game_asks_when_your_day_starts_and_ends(client):
    body = {
        "about": {"name": "Sam"},
        "companion": {"species": "blob", "name": "Mochi"},
        "day": {"wake": "07:30", "bed": "23:30"},
    }
    assert client.post("/api/onboarding", json=body).json()["ok"]
    d = get_settings().day
    assert (d.wake, d.bed_at, d.quiet_start, d.quiet_end) == (
        "07:30",
        "23:30",
        23,
        7,
    )  # quiet through the night
