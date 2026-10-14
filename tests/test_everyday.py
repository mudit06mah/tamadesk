"""Everyday play: the free shortcuts, repeating todos with habit chains, waiting-on, meetings typed
into the desk, focus sessions, and "what's next"."""

from datetime import UTC, datetime, timedelta

from tamadesk.core.config import get_settings
from tamadesk.life import actions, calendar, focus, repeat, today
from tamadesk.life.capture import parse

FRI = datetime(2026, 10, 9, 14, 0)  # a Friday afternoon, local


def local(*a) -> datetime:
    return datetime(*a).astimezone(UTC).replace(tzinfo=None)


def test_the_shortcuts_understand_everyday_phrases():
    c = parse("todo standup notes every weekday 10am #work", FRI)
    assert (c.kind, c.text, c.repeat, c.tags, c.due_at) == ("todo", "standup notes", "weekdays", ("work",),
                                                             local(2026, 10, 12, 10, 0))  # fmt: skip
    assert parse("todo invoice every month on the 1st", FRI).repeat == "monthly:1"
    assert parse("remind me to water plants every mon and thu", FRI).repeat == "weekly:0,3"
    assert (parse("done the deck", FRI).kind, parse("done the deck", FRI).target) == ("done", "the deck")
    m = parse("move invoice to monday", FRI)
    assert (m.kind, m.target, m.due_at) == ("move", "invoice", local(2026, 10, 12, 17, 0))  # a day means 5pm
    w = parse("waiting on specs from Riley by thu", FRI)
    assert (w.kind, w.text, w.who, w.due_at) == ("waiting", "specs", "Riley", local(2026, 10, 15, 10, 0))
    assert parse("waiting for the visa letter", FRI).due_at == local(2026, 10, 12, 10, 0)  # 3 days, 10am
    mt = parse("meeting design review at 3pm for 45 min", FRI)
    assert (mt.kind, mt.text, mt.minutes, mt.due_at) == (
        "meeting",
        "design review",
        45,
        local(2026, 10, 9, 15, 0),
    )
    assert parse("call mom at 6pm", FRI).text == "call mom"
    assert parse("call the bank", FRI).kind == "todo"  # no time: a todo, not a meeting
    assert (parse("focus 50 #client-a", FRI).minutes, parse("focus", FRI).minutes) == (50, 25)
    assert parse("what's next?", FRI).kind == "next"
    assert parse("todo ship it fri 9am", FRI).due_at == local(2026, 10, 16, 9, 0)  # not "Friday the 9th"
    assert parse("shipped the mockups #design", FRI).tags == ("design",)


def test_repeat_rules():
    assert repeat.next_after("weekdays", FRI, (10, 0)) == datetime(2026, 10, 12, 10, 0)  # skips the weekend
    assert repeat.next_after("weekly:3", FRI, (9, 0)) == datetime(2026, 10, 15, 9, 0)
    assert repeat.next_after("monthly:1", FRI, (9, 0)) == datetime(2026, 11, 1, 9, 0)
    assert repeat.settle("weekly:?", FRI) == "weekly:4"
    assert repeat.label("weekly:0,3") == "every Mon, Thu"


def test_a_habit_chain_grows_and_undo_and_skip_behave(conn):
    soon = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    t = actions.add_todo(conn, "stretch", soon, repeat="daily")
    r = actions.complete_todo(conn, t)
    assert (r["xp"], r["chain"]) == (15, 1)  # done + on time
    nxt = conn.execute("SELECT * FROM todos WHERE prev_id = ?", (t,)).fetchone()
    assert nxt["status"] == "open" and nxt["chain"] == 1 and nxt["due_at"] > soon
    r2 = actions.complete_todo(conn, nxt["id"])
    third = conn.execute("SELECT * FROM todos WHERE prev_id = ?", (nxt["id"],)).fetchone()
    r3 = actions.complete_todo(conn, third["id"])
    assert (r2["chain"], r3["chain"], r3["milestone"]) == (2, 3, True)  # 3 in a row: a milestone
    fourth = conn.execute("SELECT id FROM todos WHERE prev_id = ?", (third["id"],)).fetchone()[0]
    assert actions.undo_todo(conn, third["id"]) == -15  # all its XP back...
    assert conn.execute("SELECT 1 FROM todos WHERE id = ?", (fourth,)).fetchone() is None  # ...and its spawn
    actions.drop_todo(conn, third["id"])  # dropping a repeat only skips this one
    skipped = conn.execute("SELECT chain, status FROM todos WHERE prev_id = ?", (third["id"],)).fetchone()
    assert tuple(skipped) == (0, "open")


def test_waiting_on_someone(conn):
    r = actions.capture_text(conn, "waiting on specs from Riley by thu")
    assert r["message"].startswith("waiting on Riley")
    conn.execute("UPDATE todos SET due_at = datetime('now', '-1 hour') WHERE id = ?", (r["id"],))
    row = next(e for e in today.needs_you(conn) if e["key"] == f"t:{r['id']}")
    assert row["title"] == "Nudge Riley about specs?" and row["waiting"]
    assert actions.complete_todo(conn, r["id"])["xp"] == 5  # it arrived: no deadline bonus for others' work
    assert actions.undo_todo(conn, r["id"]) == -5


def test_done_move_and_next_by_name(conn):
    actions.capture_text(conn, "todo send the invoice to Acme")
    actions.capture_text(conn, "todo book dentist")
    assert actions.capture_text(conn, "move invoice to tomorrow 5pm")["message"].startswith(
        "moved send the invoice"
    )
    assert "Pick this one: book dentist" == actions.capture_text(conn, "next")["message"]
    r = actions.capture_text(conn, "done invoice")
    assert (r["kind"], r["text"], r["xp"]) == ("done", "send the invoice to Acme", 15)
    nothing = actions.capture_text(conn, "done walked the dog")  # nothing to tick: it goes in the log
    assert (nothing["kind"], nothing["xp"]) == ("log", 5)


def test_a_typed_meeting_rings_like_an_invite(conn):
    s = get_settings()
    start = datetime.now(UTC).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=8)
    calendar.add_local(conn, "design review", start, 45)
    [m] = [e for e in today.day(conn)["timeline"] if e["kind"] == "meeting"]
    assert m["title"] == "design review"
    assert calendar.alerts(s, conn) == 1  # inside the 10-minute ring window


def test_focus_sessions(conn):
    t0 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    f = focus.start(conn, 25, "client-a", now=t0)
    assert focus.finish_due(conn, t0 + timedelta(minutes=10)) is None  # not yet
    done = focus.finish_due(conn, t0 + timedelta(minutes=26))
    assert (done["id"], done["xp"]) == (f["id"], 10)
    focus.start(conn, 50, "client-a", now=t0 + timedelta(hours=1))
    focus.start(conn, 25, "", now=t0 + timedelta(hours=1, minutes=20))  # starting another stops the first
    focus.stop(conn, now=t0 + timedelta(hours=1, minutes=30))
    assert focus.minutes_by_tag(conn, "2026-10-09 00:00:00", "2026-10-10 00:00:00") == {"client-a": 45,
                                                                                       "untagged": 10}  # fmt: skip
    xp = conn.execute("SELECT sum(xp) FROM events WHERE kind LIKE 'focus%'").fetchone()[0]
    assert xp == 10  # stopping early earns nothing


def test_a_repeating_todo_never_doubles_and_can_be_removed(conn):
    """The real sequence that left two copies: tick it, skip the next, undo the first, skip it again."""
    from tamadesk.assistant import tools

    first = actions.capture_text(conn, "todo workout 3 times every friday")["id"]
    open_copies = lambda: conn.execute(
        "SELECT id FROM todos WHERE title = 'workout 3 times' AND status = 'open'"
    ).fetchall()
    actions.complete_todo(conn, first)
    actions.drop_todo(conn, open_copies()[0][0])  # skip next week's
    actions.undo_todo(conn, first)
    actions.drop_todo(conn, first)  # skip it again
    assert len(open_copies()) == 1
    r = actions.capture_text(conn, "remove workout reminder")
    assert (r["kind"], r["message"]) == ("remove", "removed: workout 3 times (it won't repeat)")
    assert open_copies() == []
    actions.capture_text(conn, "remind me to stretch at 6pm")
    assert (
        actions.capture_text(conn, "cancel the stretch reminder")["message"] == "reminder cancelled: stretch"
    )
    t = actions.capture_text(conn, "todo water plants every day")["id"]
    assert tools.drop_todo(get_settings(), conn, t) == "removed 'water plants' and stopped it repeating"
    assert tools.list_todos(get_settings(), conn)["open"] == []
