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
TIMEY = re.compile(
    r"\d|\b(?:today|tonight|tomorrow|noon|midnight|morning|evening|afternoon|week|"
    r"mon|tue|wed|thu|fri|sat|sun)\w*\b",
    re.IGNORECASE,
)


@dataclass
class Capture:
    kind: str  # todo | reminder | log
    text: str
    due_at: datetime | None = None  # naive UTC


def _find_time(text: str, now: datetime) -> tuple[str, datetime | None]:
    found = search_dates(
        text,
        languages=["en"],
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now, "RETURN_AS_TIMEZONE_AWARE": False},
    )
    for phrase, when in found or []:
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
        return Capture("reminder" if when else "todo", rest or text, _to_utc(when))
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
