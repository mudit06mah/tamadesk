"""Time in one place. The database stores naive UTC ('YYYY-MM-DD HH:MM:SS', what SQLite's
datetime('now') writes); people live in local time. Every conversion between the two goes through here.

A "day" is the user's day, not the calendar's: it turns over halfway through their night (bed 01:00,
wake 09:00 -> 05:00). So 12:30am still counts as today, the bedtime recap covers the day that began
when they woke, and an earlier-than-usual morning already counts as the new day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta


def utc(ts: str) -> datetime:
    """A stored UTC timestamp as an aware UTC datetime."""
    return datetime.fromisoformat(ts).replace(tzinfo=UTC)


def local(ts: str) -> datetime:
    """A stored UTC timestamp as the user's local time (timezone-aware)."""
    return utc(ts).astimezone()


def local_naive(ts: str) -> datetime:
    """The same, without the timezone: for comparing with naive local times (parsed phrases)."""
    return local(ts).replace(tzinfo=None)


def to_utc(when: datetime | None) -> datetime | None:
    """A local time (naive means the machine's zone) as naive UTC, ready to store."""
    return None if when is None else when.astimezone(UTC).replace(tzinfo=None)


def sql_ts(dt: datetime) -> str:
    """A naive UTC datetime in SQLite's datetime('now') format."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def turn_minutes(wake: str | None = None, bed: str | None = None) -> int:
    """Minutes after midnight when one of the user's days becomes the next: halfway through their night."""
    if wake is None or bed is None:
        from tamadesk.core.config import get_settings

        d = get_settings().day
        wake, bed = d.wake, d.bed_at
    b, w = _minutes(bed), _minutes(wake)
    night = (w - b) % 1440 or 480  # bed == wake makes no sense: assume 8 hours
    return (b + night // 2) % 1440


def today(now: datetime | None = None) -> date:
    """The user's current day (still yesterday's date at 12:30am if they haven't slept yet)."""
    return ((now or datetime.now().astimezone()) - timedelta(minutes=turn_minutes())).date()


def day_of(ts: str) -> date:
    """The user's day a stored UTC timestamp belongs to."""
    return (local(ts) - timedelta(minutes=turn_minutes())).date()


def at_on(d: date, hm: str) -> datetime:
    """The local moment 'HH:MM' on the user's day `d` (a time before the turnover is the night after)."""
    t = _minutes(hm)
    when = datetime.combine(d, time(t // 60, t % 60)).astimezone()
    return when + timedelta(days=1) if t < turn_minutes() else when


def day_bounds(d: date) -> tuple[str, str]:
    """The user's day `d` as [start, end) stored-UTC timestamps."""
    t = turn_minutes()
    start = datetime.combine(d, time(t // 60, t % 60)).astimezone()
    end = datetime.combine(d + timedelta(days=1), time(t // 60, t % 60)).astimezone()
    return sql_ts(to_utc(start)), sql_ts(to_utc(end))


def day_start_utc() -> str:
    """When the user's current day began, as a stored-UTC timestamp."""
    return day_bounds(today())[0]
