"""Deadlines: set them in plain words, feel the pressure build as they get close, and earn a bonus for
beating one (undo takes all of it back)."""

from datetime import UTC, datetime, timedelta

from tamadesk.assistant import tools
from tamadesk.core import db
from tamadesk.core.clock import sql_ts as ts
from tamadesk.core.config import get_settings
from tamadesk.life import actions, pressure, today

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_stages_and_tone_follow_the_clock_and_the_users_words():
    assert [pressure.stage(timedelta(hours=h)) for h in (30, 20, 2, 0.5, -1)] == [0, 1, 2, 3, 4]
    assert pressure.tone("strict coach please") == "strict"
    assert pressure.tone("hype-man!") == "hype"
    assert pressure.tone("deadpan") == "deadpan"
    assert pressure.tone("") == "gentle"
    assert (
        pressure.line("Ship deck", NOW + timedelta(hours=2), NOW, "strict")
        == '"Ship deck": 2h left. Stop what you\'re doing and start.'
    )
    assert "was due 30m ago" in pressure.line("Ship deck", NOW - timedelta(minutes=30), NOW, "gentle")


def test_each_stage_pings_once_and_a_jump_pings_only_where_it_lands(conn):
    t = actions.add_todo(conn, "Ship deck", ts(NOW + timedelta(hours=30)))
    assert pressure.due_nudges(conn, "gentle", NOW) == []  # more than a day out: calm
    assert len(pressure.due_nudges(conn, "gentle", NOW + timedelta(hours=7))) == 1  # within a day
    assert pressure.due_nudges(conn, "gentle", NOW + timedelta(hours=8)) == []  # not twice
    jumped = pressure.due_nudges(conn, "gentle", NOW + timedelta(hours=29, minutes=30))  # straight to "hour"
    assert len(jumped) == 1
    assert pressure.due_nudges(conn, "gentle", NOW + timedelta(hours=29, minutes=45)) == []
    actions.set_due(conn, t, "in 3 days")  # a new deadline starts calm again
    assert conn.execute("SELECT nudged FROM todos WHERE id = ?", (t,)).fetchone()[0] == 0


def test_deadlines_are_set_in_plain_words(client, conn):
    t = actions.add_todo(conn, "Ship deck")
    due = client.put(f"/api/todos/{t}/due", json={"when": "in 2 days"}).json()["due_at"]
    assert abs(
        datetime.fromisoformat(due).replace(tzinfo=UTC) - (datetime.now(UTC) + timedelta(days=2))
    ) < timedelta(minutes=2)
    assert client.put(f"/api/todos/{t}/due", json={"when": "whenever"}).status_code == 422
    assert client.put(f"/api/todos/{t}/due", json={"when": ""}).json() == {"due_at": None}
    assert tools.set_deadline(get_settings(), conn, t, "tomorrow 5pm").startswith("deadline ")
    # the clock picker sends an exact local time; a time already gone is refused
    soon = (datetime.now() + timedelta(days=1)).replace(hour=17, minute=30)
    due = client.put(f"/api/todos/{t}/due", json={"when": f"{soon:%Y-%m-%d %H:%M}"}).json()["due_at"]
    assert datetime.fromisoformat(due).replace(tzinfo=UTC).astimezone().replace(tzinfo=None) == soon.replace(
        second=0, microsecond=0
    )
    assert client.put(f"/api/todos/{t}/due", json={"when": "2020-01-01 09:00"}).status_code == 422
    assert tools.set_deadline(get_settings(), conn, t, "") == "deadline cleared"


def test_beating_a_deadline_earns_a_bonus_and_undo_takes_it_all_back(client, conn):
    def xp():
        return client.get("/api/state").json()["progress"]["xp"]

    base = xp()
    early = actions.add_todo(conn, "Ship deck", ts(datetime.now(UTC) + timedelta(hours=3)))
    assert client.post(f"/api/todos/{early}/done").json()["xp"] == 15
    late = actions.add_todo(conn, "Pay invoice", ts(datetime.now(UTC) - timedelta(hours=3)))
    assert client.post(f"/api/todos/{late}/done").json()["xp"] == 10
    assert xp() == base + 25
    client.post(f"/api/todos/{early}/undo")
    client.post(f"/api/todos/{late}/undo")
    assert xp() == base


def test_today_carries_the_most_pressing_deadline_in_the_users_style(conn):
    db.set_profile(conn, "about", {"nudge": "strict coach"})
    actions.add_todo(conn, "Ship deck", ts(datetime.now(UTC) + timedelta(minutes=40)))
    actions.add_todo(conn, "Later thing", ts(datetime.now(UTC) + timedelta(days=5)))
    p = today.day(conn)["pressure"]
    assert p["stage"] == 3 and p["text"].startswith('"Ship deck" is due in') and "No more delays" in p["text"]
