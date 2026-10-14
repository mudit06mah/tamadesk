"""Repeating todos and reminders: "every weekday", "every mon and thu 9am", "monthly on the 15th".

A rule is a short string stored on the row: daily | weekdays | weekly:0,3 (Mon=0) | monthly:15.
Finishing (or skipping) a repeating todo makes the next one; a repeating reminder schedules its next
ring when it fires. Finishing on time grows the habit chain, which the UI celebrates at milestones.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
EVERY = re.compile(
    r"\b(?:every\s+(?P<what>day|weekday|week ?day|weekend|week|month|morning|evening|night|"
    r"(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*(?:\s*(?:,|and|&)\s*)?)+|\d{1,2}(?:st|nd|rd|th)?(?: of the month)?)"
    r"|(?P<adverb>daily|weekly|monthly|weekdays))\b",
    re.IGNORECASE,
)
MILESTONES = (3, 7, 14, 30, 50, 100)


def parse(text: str) -> tuple[str, str | None, str | None]:
    """Text -> (text without the rule, rule, a time-of-day hint like 'morning'). No rule -> (text, None, None)."""
    m = EVERY.search(text)
    if not m:
        return text, None, None
    what = (m.group("what") or m.group("adverb") or "").lower().replace(" ", "")
    hint = what if what in ("morning", "evening", "night") else None
    if what in ("day", "daily", "morning", "evening", "night"):
        rule = "daily"
    elif what in ("weekday", "weekdays"):
        rule = "weekdays"
    elif what == "weekend":
        rule = "weekly:5,6"
    elif what in ("week", "weekly"):
        rule = "weekly:?"  # the same weekday as the first one: see settle()
    elif what in ("month", "monthly"):
        rule = "monthly:?"
    elif day := re.match(r"(\d{1,2})", what):
        rule = f"monthly:{min(int(day.group(1)), 28)}"  # the 29th-31st don't exist every month
    else:
        found = sorted({DAYS.index(d[:3]) for d in re.findall(r"(mon|tue|wed|thu|fri|sat|sun)", what)})
        rule = "weekly:" + ",".join(map(str, found))
    rest = re.sub(r"\s+", " ", (text[: m.start()] + text[m.end() :])).strip(" ,")
    if rule == "monthly:?" and (
        nth := re.search(r"\b(?:on\s+)?the\s+(\d{1,2})(?:st|nd|rd|th)\b", rest, re.IGNORECASE)
    ):
        rule = f"monthly:{min(int(nth.group(1)), 28)}"  # "every month on the 1st"
        rest = re.sub(r"\s+", " ", rest[: nth.start()] + rest[nth.end() :]).strip(" ,")
    return rest, rule, hint


def _matches(rule: str, d: datetime) -> bool:
    kind, _, arg = rule.partition(":")
    if kind == "daily":
        return True
    if kind == "weekdays":
        return d.weekday() < 5
    if kind == "weekly":
        return d.weekday() in {int(x) for x in arg.split(",")}
    if kind == "monthly":
        return d.day == int(arg)
    return False


def settle(rule: str, first: datetime) -> str:
    """'every week' / 'every month' take their day from the first occurrence."""
    if rule == "weekly:?":
        return f"weekly:{first.weekday()}"
    if rule == "monthly:?":
        return f"monthly:{min(first.day, 28)}"
    return rule


def next_after(rule: str, after: datetime, at: tuple[int, int]) -> datetime:
    """The first occurrence strictly after `after` (naive local), at hour:minute `at`."""
    d = after.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    if d <= after:
        d += timedelta(days=1)
    for _ in range(400):
        if _matches(rule, d):
            return d
        d += timedelta(days=1)
    raise ValueError(f"rule {rule!r} never happens")


def label(rule: str | None) -> str:
    """For the UI: 'every day', 'weekdays', 'every Mon, Thu', 'monthly on the 15th'."""
    if not rule:
        return ""
    kind, _, arg = rule.partition(":")
    if kind == "weekly":
        return "every " + ", ".join(DAYS[int(x)].title() for x in arg.split(","))
    if kind == "monthly":
        return f"monthly on the {arg}"
    return {"daily": "every day", "weekdays": "weekdays"}[kind]


def milestone(chain: int) -> bool:
    """Is this habit chain length worth a celebration?"""
    return chain in MILESTONES
