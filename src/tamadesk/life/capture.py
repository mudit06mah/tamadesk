"""Quick capture: one text box that figures out whether you wrote a todo, a reminder or a log line.

    "todo buy milk" / "[] buy milk" / "- [ ] buy milk"  -> todo
    "remind me to call mom at 6pm" / "remind me in 20 min to stretch" -> reminder
    anything else                                   -> daily log entry

Pure function (no DB) so it's easy to test; times come back as naive UTC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from dateparser.search import search_dates

TODO_RE = re.compile(r"^\s*(?:todo\b[:\s]*|t:\s*|\[\s?\]\s*|-\s*\[\s?\]\s*)", re.IGNORECASE)
REMIND_RE = re.compile(r"^\s*remind\s+me\s+(?:to\s+)?", re.IGNORECASE)
# dateparser happily reads "a", "to" or "me" as dates; only accept matches that look like times
# a phrase only counts as a time if it looks like one: a bare number ("PR 4521") does not
TIMEY = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b"  # 6pm, 9:30, 18:00
    r"|\b\d+\s*(?:minutes?|hours?|days?|weeks?|months?)\b"  # in 20 minutes
    r"|\b\d{1,2}(?:st|nd|rd|th)\b|\b\d{1,2}[/.-]\d{1,2}\b"  # the 5th, 10/12
    r"|\b(?:today|tonight|tomorrow|noon|midnight|morning|evening|afternoon|next week|this week|weekend"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|mon|tue|wed|thu|fri|sat|sun)\w*\b",
    re.IGNORECASE,
)
# dateparser drops the clock time next to a relative day ("tomorrow 10am" -> tomorrow at the current time)
CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", re.IGNORECASE)


def _with_clock(phrase: str, when: datetime) -> datetime:
    """Apply an explicit clock time in `phrase` to the day dateparser picked."""
    if not (m := CLOCK.search(phrase)):
        return when
    if m.group(3):
        hour, minute = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0), int(m.group(2) or 0)
    else:
        hour, minute = int(m.group(4)), int(m.group(5))
    if hour > 23 or minute > 59:
        return when
    return when.replace(hour=hour, minute=minute, second=0, microsecond=0)


@dataclass
class Capture:
    kind: str  # todo | reminder | log
    text: str
    due_at: datetime | None = None  # naive UTC
    no_time: bool = False  # asked for a reminder but no time was found, so it became a todo


# phrasings people use that the date parser doesn't know: "after a minute", "half an hour", "in an hour"
NORMALIZE = [
    (re.compile(r"\bhalf an? hour\b", re.IGNORECASE), "30 minutes"),
    (re.compile(r"\ban? (minute|min|hour|hr|day|week)\b", re.IGNORECASE), r"1 \1"),
    (re.compile(r"\b(?:after|within)\s+(?=\d)", re.IGNORECASE), "in "),
    (re.compile(r"\b(\d+)\s*(mins?|m)\b", re.IGNORECASE), r"\1 minutes"),
    (re.compile(r"\b(\d+)\s*(hrs?|h)\b", re.IGNORECASE), r"\1 hours"),
]


def _normalize(text: str) -> str:
    for rx, rep in NORMALIZE:
        text = rx.sub(rep, text)
    return text


def _find_time(text: str, now: datetime) -> tuple[str, datetime | None]:
    text = _normalize(text)
    found = search_dates(
        text,
        languages=["en"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now, "RETURN_AS_TIMEZONE_AWARE": False},
    )
    for phrase, when in found or []:
        when = _with_clock(phrase, when)
        if TIMEY.search(phrase) and when > now:
            rest = text.replace(phrase, " ", 1)
            rest = re.sub(r"\s+(?:at|on|in|by)\s*$", "", re.sub(r"\s+", " ", rest).strip())
            rest = re.sub(r"^(?:(?:at|on|in|by)\s+)?(?:to\s+)?", "", rest).strip()
            return rest, when
    return text, None


def parse(text: str, now: datetime | None = None) -> Capture:
    """`now` is naive *local* time (what the user means by "6pm"); due_at is returned in UTC."""
    now = now or datetime.now(UTC).astimezone().replace(tzinfo=None)
    text = text.strip()
    if m := REMIND_RE.match(text):
        rest, when = _find_time(text[m.end() :], now)
        return Capture("reminder" if when else "todo", rest or text, _to_utc(when), no_time=when is None)
    if m := TODO_RE.match(text):
        rest, when = _find_time(text[m.end() :], now)
        return Capture("todo", rest or text[m.end() :].strip(), _to_utc(when))
    return Capture("log", text)


def _to_utc(local: datetime | None) -> datetime | None:
    if local is None:
        return None
    return local.astimezone(UTC).replace(tzinfo=None)


def sql_ts(dt: datetime) -> str:
    """Naive UTC datetime -> SQLite datetime('now') format."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")
