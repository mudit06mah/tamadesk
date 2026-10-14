from datetime import date

from tamadesk.life.game import level_for, streak_with_freezes


def streak(days, today):
    return streak_with_freezes(days, today)[0]


def test_levels():
    assert level_for(0) == (1, 0, 100)
    assert level_for(99) == (1, 99, 100)
    assert level_for(100) == (2, 0, 150)
    assert level_for(260) == (3, 10, 200)


def test_streak_counts_back_from_today_or_yesterday():
    d = date(2026, 10, 3)
    days = {date(2026, 10, 1), date(2026, 10, 2)}
    assert streak(days, d) == 2  # nothing yet today, but yesterday keeps it alive
    assert streak(days | {d}, d) == 3
    assert streak({date(2026, 9, 30)}, d) == 0
