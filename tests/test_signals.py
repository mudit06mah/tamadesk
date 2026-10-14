"""The feel of it: notifications with manners, streak freezes, tips, the week card, standups,
promises after meetings, and GitHub asks on Today."""

from datetime import UTC, date, datetime, timedelta

from tamadesk.core.config import get_settings
from tamadesk.life import actions, calendar, focus, game, github, notify, review, tips, today


def test_urgent_rings_now_the_rest_waits_for_a_good_moment(conn):
    s = get_settings()
    sent = []
    send = lambda t, b: sent.append(t)
    s.day.quiet_start, s.day.quiet_end = 22, 8
    try:
        assert notify.quiet(s, datetime(2026, 10, 9, 23, 0)) and notify.quiet(s, datetime(2026, 10, 9, 7, 59))
        assert not notify.quiet(s, datetime(2026, 10, 9, 12, 0))
    finally:
        s.day.quiet_start = s.day.quiet_end = None
    focus.start(conn, 25)
    assert notify.ping(s, conn, "reminder", "Call mom", "now", send=send)  # urgent: rings through focus
    assert not notify.ping(s, conn, "inbox", "New reply", "Riley", send=send)  # waits
    assert not notify.ping(s, conn, "tab", "Papers", "3 new", send=send)
    assert notify.flush(s, conn, send=send) == 0  # still focusing
    focus.stop(conn)
    assert notify.flush(s, conn, send=send) == 2
    assert sent == ["Call mom", "While you were away: 2 updates"]
    assert not notify.ping(s, conn, "tab", "Papers", "1 new", send=send)  # tab pings are always batched


def test_a_missed_day_spends_a_freeze_instead_of_the_streak():
    d0 = date(2026, 9, 1)
    week = {d0 + timedelta(days=i) for i in range(7)}  # 7 in a row earns a freeze
    gap = week | {d0 + timedelta(days=8), d0 + timedelta(days=9)}  # day 8 (index 7) missed
    assert game.streak_with_freezes(week, d0 + timedelta(days=6)) == (7, 1, [])
    n, left, frozen = game.streak_with_freezes(gap, d0 + timedelta(days=9))
    assert (n, left, frozen) == (9, 0, [d0 + timedelta(days=7)])
    two_gaps = gap | {d0 + timedelta(days=11)}  # missed day 10 too, no freeze left
    assert game.streak_with_freezes(two_gaps, d0 + timedelta(days=11))[0] == 1
    assert game.streak_with_freezes(week, d0 + timedelta(days=7))[0] == 7  # today isn't over yet


def test_tips_suggest_shortcuts_you_have_not_tried_yet(conn):
    assert tips.untried(conn) == ["todo send the invoice fri 5pm", "todo stretch every weekday 11am"]
    actions.capture_text(conn, "todo stretch every weekday 11am")  # a habit with a deadline: both learned
    assert tips.untried(conn) == ["focus 25", "waiting on the specs from Alex by thu"]


def test_standup_and_the_week_card(conn):
    actions.capture_text(conn, "todo ship the onboarding flow #acme")
    actions.capture_text(conn, "done onboarding")
    actions.capture_text(conn, "waiting on specs from Riley")
    w = review.week(conn)
    assert (w["done"], w["title"]) == (1, "Getting Going") and "ship the onboarding flow #acme" in w[
        "highlights"
    ]
    assert w["markdown"].startswith("## Week of")
    tomorrow = today.local_today() + timedelta(days=1)
    s = review.standup(conn, tomorrow)
    if tomorrow.weekday() == 0:  # Monday's "yesterday" is Friday, not the weekend
        assert "(Fri)" in s["markdown"]
    elif today.local_today().weekday() < 5:
        assert "ship the onboarding flow" in s["yesterday"]
    assert s["blockers"] == []  # waiting on Riley isn't due for a follow-up yet
    brag = review.brag(conn, today.local_today() - timedelta(days=7))
    assert "**#acme**" in brag["markdown"]


def test_after_a_meeting_it_asks_what_you_promised(client, conn):
    start = datetime.now(UTC).replace(microsecond=0, tzinfo=None) - timedelta(minutes=50)
    calendar.add_local(conn, "Design review", start, 30)  # ended 20 minutes ago
    [row] = [e for e in today.needs_you(conn) if e["kind"] == "promise"]
    assert row["title"] == "Design review ended: anything you promised?"
    r = client.post("/api/meetings/promises", json={"cal_key": row["ref"]["cal_key"],
                                                    "lines": ["send the deck", " ", "intro Alex to Sam"]})  # fmt: skip
    assert len(r.json()["todos"]) == 2
    assert not [e for e in today.needs_you(conn) if e["kind"] == "promise"]  # asked once


def test_github_asks_show_up_from_the_cache_and_can_be_dismissed(client, conn, monkeypatch):
    note = {"id": "123", "reason": "review requested", "title": "Fix the parser", "repo": "o/r",
            "url": "https://github.com/o/r/pull/9", "updated_at": "2026-10-09T10:00:00Z"}  # fmt: skip
    monkeypatch.setitem(github._cache, "data", {"notifications": [note], "shipped": []})
    [row] = [e for e in today.needs_you(conn) if e.get("next", {}).get("kind") == "github"]
    assert (row["title"], row["link"]) == ("Fix the parser", "https://github.com/o/r/pull/9")
    client.post("/api/seen", json={"kind": "gh", "key": "123"})
    assert not [e for e in today.needs_you(conn) if e.get("next", {}).get("kind") == "github"]
    assert (
        github._html("https://api.github.com/repos/o/r/issues/4", "o/r") == "https://github.com/o/r/issues/4"
    )
