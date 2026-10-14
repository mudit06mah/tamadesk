"""Quick capture: one text box that understands the everyday things, instantly and for free.

    "todo buy milk #home" / "[] buy milk"              -> todo (with tags)
    "todo standup notes every weekday 10am"            -> a repeating todo
    "remind me to call mom at 6pm" / "... every sunday" -> reminder (repeating too)
    "done invoice" / "finished the deck"               -> ticks the open todo that matches
    "move invoice to friday"                           -> gives it a new deadline
    "remove workout" / "cancel the stretch reminder"   -> removes it (a repeating one stops for good)
    "waiting on specs from Riley by thu"               -> something you're waiting on, with a follow-up day
    "meeting design review at 3pm for 45 min"          -> an event on your timeline, with a ring before it
    "focus 25 #client-a"                               -> a focus session
    "next" / "what's next?"                            -> the one thing to do now
    anything else                                      -> daily log entry

Pure function (no DB) so it's easy to test; times come back as naive UTC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dateparser.search import search_dates

from tamadesk.core.clock import to_utc
from tamadesk.life import repeat as repeating

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


TAG = re.compile(r"(?<![\w&])#([\w][\w-]{0,29})")
NEXT_RE = re.compile(r"^\s*(?:next|what'?s next|what now|now what)\s*\??\s*$|^\s*\?\s*$", re.IGNORECASE)
FOCUS_RE = re.compile(r"^\s*focus\b(?:\s+(?:for\s+)?(\d{1,3})\s*(?:m|min|mins|minutes)?)?\s*$", re.IGNORECASE)
REMOVE_RE = re.compile(
    r"^\s*(?:remove|delete|drop|cancel|stop)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:reminder|todo|habit|task))?\s*$",
    re.IGNORECASE,
)
DONE_RE = re.compile(r"^\s*(?:done|finished|✓)\s*:?\s+(.+)$", re.IGNORECASE)
MOVE_RE = re.compile(r"^\s*(?:move|push|snooze|postpone)\s+(.+?)\s+(?:to|until|till)\s+(.+)$", re.IGNORECASE)
WAIT_RE = re.compile(
    r"^\s*waiting\s+(?:on|for)\s+(.+?)(?:\s+from\s+([\w.' -]+?))?(?:\s+(?:by|until|till)\s+(.+))?\s*$",
    re.IGNORECASE,
)
MEET_RE = re.compile(r"^\s*(?:meeting|mtg|call|meet)\b\s*:?\s*(.*)$", re.IGNORECASE)
LENGTH_RE = re.compile(r"\bfor\s+(\d{1,3})\s*(m|min|mins|minutes|h|hr|hrs|hours?)\b", re.IGNORECASE)
# the words any of these start with, so the Ask box knows a line is free (kept in sync with AskStore.FREE)
VERBS = ["todo", "t:", "[]", "remind me", "log", ">", "done", "finished", "move", "push", "snooze", "postpone",
         "waiting on", "waiting for", "meeting", "mtg", "call", "meet", "focus", "next", "what's next", "?",
         "remove", "delete", "drop", "cancel", "stop"]  # fmt: skip
DEFAULT_AT = {"todo": (17, 0), "reminder": (9, 0), "morning": (9, 0), "evening": (18, 0), "night": (21, 0)}


@dataclass
class Capture:
    """What a line typed on the desk means: its kind, text, time and details."""

    kind: str  # todo | reminder | log | done | move | waiting | meeting | focus | next | remove
    text: str
    due_at: datetime | None = None  # naive UTC
    no_time: bool = False  # asked for a reminder but no time was found, so it became a todo
    tags: tuple[str, ...] = ()
    repeat: str | None = None  # a rule from life/repeat.py
    who: str | None = None  # waiting on whom
    minutes: int | None = None  # focus length, or meeting length
    target: str | None = None  # done / move: the words that name the todo


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


# "fri 9am", "on monday at 10:30": read here, because dateparser takes "fri 9am" on the 9th of a month
# for "Friday the 9th"
WEEKDAY_CLOCK = re.compile(
    r"\b(?:on\s+)?(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2})\b",
    re.IGNORECASE,
)


def _weekday_clock(text: str, now: datetime) -> tuple[str, datetime | None]:
    m = WEEKDAY_CLOCK.search(text)
    if not m:
        return text, None
    day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(m.group(1).lower())
    when = _with_clock(m.group(2), now)
    when += timedelta(days=(day - now.weekday()) % 7)
    if when <= now:
        when += timedelta(days=7)
    rest = re.sub(r"\s+", " ", text[: m.start()] + text[m.end() :]).strip()
    return re.sub(r"\s+(?:at|on|by)$", "", rest), when


def find_time(text: str, now: datetime) -> tuple[str, datetime | None]:
    """The first time to come in `text` ("fri 5pm", "in 2 days") and the text without it; None if none."""
    text = _normalize(text)
    rest, when = _weekday_clock(text, now)
    if when is not None:
        return rest, when
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


def day_only(when: datetime | None, phrase: str, at: tuple[int, int]) -> datetime | None:
    """'friday' with no clock time means a sensible hour that day, not midnight."""
    if when is None or CLOCK.search(phrase) or (when.hour, when.minute) != (0, 0):
        return when
    return when.replace(hour=at[0], minute=at[1])


def _tags(text: str) -> tuple[str, tuple[str, ...]]:
    tags = tuple(dict.fromkeys(t.lower() for t in TAG.findall(text)))
    return re.sub(r"\s+", " ", TAG.sub(" ", text)).strip(), tags


def _repeating(kind: str, body: str, now: datetime) -> tuple[str, str | None, datetime | None]:
    """'standup notes every weekday 10am' -> ('standup notes', 'weekdays', the first one)."""
    rest, rule, hint = repeating.parse(body)
    if rule is None:
        return body, None, None
    rest, when = find_time(rest, now)
    at = (when.hour, when.minute) if when else DEFAULT_AT[hint or kind]
    rule = repeating.settle(rule, when or now)
    return rest, rule, repeating.next_after(rule, now, at)


def parse(text: str, now: datetime | None = None) -> Capture:
    """`now` is naive *local* time (what the user means by "6pm"); due_at is returned in UTC."""
    now = now or datetime.now(UTC).astimezone().replace(tzinfo=None)
    text, tags = _tags(text.strip())
    if NEXT_RE.match(text):
        return Capture("next", "")
    if m := FOCUS_RE.match(text):
        return Capture("focus", "", tags=tags, minutes=max(5, min(int(m.group(1) or 25), 180)))
    if m := REMOVE_RE.match(text):
        return Capture("remove", m.group(1).strip(), target=m.group(1).strip())
    if m := DONE_RE.match(text):
        return Capture("done", m.group(1).strip(), tags=tags, target=m.group(1).strip())
    if m := MOVE_RE.match(text):
        when = day_only(find_time(m.group(2), now)[1], m.group(2), DEFAULT_AT["todo"])
        return Capture(
            "move", m.group(2).strip(), to_utc(when), no_time=when is None, target=m.group(1).strip()
        )
    if m := WAIT_RE.match(text):
        when = day_only(find_time(m.group(3), now)[1], m.group(3), (10, 0)) if m.group(3) else None
        when = when or (now + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
        return Capture(
            "waiting", m.group(1).strip(), to_utc(when), tags=tags, who=(m.group(2) or "").strip() or None
        )
    if (m := MEET_RE.match(text)) and m.group(1):
        body, length = m.group(1), 30
        if ln := LENGTH_RE.search(body):
            length = int(ln.group(1)) * (60 if ln.group(2).lower().startswith("h") else 1)
            body = (body[: ln.start()] + body[ln.end() :]).strip()
        rest, when = find_time(body, now)
        if m.group(0).strip().lower().startswith(("call", "meet ")):  # "call mom" keeps its verb
            rest = f"{m.group(0).split()[0].lower()} {rest}".strip()
        if when:
            return Capture("meeting", rest or body, to_utc(when), tags=tags, minutes=max(5, min(length, 600)))
        return Capture("todo", m.group(0).strip(), tags=tags, no_time=True)
    if m := REMIND_RE.match(text):
        rest, rule, first = _repeating("reminder", text[m.end() :], now)
        if rule:
            return Capture("reminder", rest or text, to_utc(first), tags=tags, repeat=rule)
        rest, when = find_time(text[m.end() :], now)
        return Capture(
            "reminder" if when else "todo", rest or text, to_utc(when), no_time=when is None, tags=tags
        )
    if m := TODO_RE.match(text):
        rest, rule, first = _repeating("todo", text[m.end() :], now)
        if rule:
            return Capture("todo", rest or text[m.end() :].strip(), to_utc(first), tags=tags, repeat=rule)
        rest, when = find_time(text[m.end() :], now)
        when = day_only(when, text[m.end() :], DEFAULT_AT["todo"])
        return Capture("todo", rest or text[m.end() :].strip(), to_utc(when), tags=tags)
    return Capture("log", text, tags=tags)
