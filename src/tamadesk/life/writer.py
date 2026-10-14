"""What the light brain writes outside the assistant: the voice profile and the evening recap.

The voice profile is built once from the user's own writing samples, then reused, so drafts sound
like the user and not like a chatbot.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

from tamadesk.brain import Brain
from tamadesk.core import clock, db
from tamadesk.core.config import get_settings

VOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences on how this person writes"},
        "traits": {"type": "array", "items": {"type": "string"}},
        "do": {"type": "array", "items": {"type": "string"}},
        "dont": {"type": "array", "items": {"type": "string"}},
        "phrases": {"type": "array", "items": {"type": "string"}, "description": "real phrases they use"},
    },
    "required": ["summary", "traits", "do", "dont", "phrases"],
}

RECAP_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "one upbeat line, under 10 words"},
        "recap": {"type": "string", "description": "3-5 sentences, second person, honest"},
        "tomorrow": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["todo", "text"],
                "properties": {
                    "todo": {"type": "integer", "description": "the open todo's number, or 0 for a new idea"},
                    "text": {"type": "string"},
                },
            },
        },
    },
    "required": ["headline", "recap", "tomorrow"],
}


# emoji -> the closest emoticon (tamadesk speaks in :) not 😊); anything else pictographic is dropped
EMOTICONS = {
    "😊": ":)", "🙂": ":)", "😀": ":D", "😃": ":D", "😄": ":D", "😁": ":D", "😆": "XD", "😂": "XD", "🤣": "XD",
    "😉": ";)", "😜": ";P", "😛": ":P", "😢": ":(", "😞": ":(", "🙁": ":(", "😭": "T_T", "😮": ":O", "😲": ":O",
    "😅": "^^;", "😍": "<3", "❤️": "<3", "❤": "<3", "💖": "<3", "😎": "B)", "🤔": "hmm", "👍": "+1", "🎉": "\\o/",
    "🥳": "\\o/", "😴": "-_-zzz", "🙏": "thanks", "😬": ":S", "😐": ":|", "😑": "-_-",
}  # fmt: skip
EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\U0001f1e6-\U0001f1ff\ufe0f\u200d\u20e3]+"
)


def no_emoji(text: str) -> str:
    """Strip emoji: the companion uses text emoticons only."""
    for e, face in EMOTICONS.items():
        text = text.replace(e, face)
    return re.sub(r"[ \t]{2,}", " ", EMOJI.sub("", text))


def clean(text: str) -> str:
    """Deterministic last pass on anything written for the user: no em dashes, no emoji."""
    return no_emoji(re.sub(r"\s*[\u2014\u2013]\s*", ", ", text))


def _about(conn: sqlite3.Connection) -> str:
    about = db.get_profile(conn, "about", {})
    return "\n".join(f"- {k}: {v}" for k, v in about.items() if v)


def build_voice(conn: sqlite3.Connection, brain: Brain) -> dict:
    """Describe how the user writes, from their samples and sent mail (light brain), and keep it for drafts."""
    samples = conn.execute("SELECT kind, title, body FROM samples ORDER BY id").fetchall()
    # what they actually sent (after their own edits) is the best evidence of their voice
    sent = conn.execute("SELECT 'sent email' AS kind, subject AS title, body FROM drafts WHERE status = 'sent' "
                        "ORDER BY sent_at DESC LIMIT 10").fetchall()  # fmt: skip
    if not samples and not sent:
        raise ValueError("add a writing sample (or send an email from Mail) first")
    text = "\n\n".join(
        f"### {r['kind']}: {r['title'] or 'untitled'}\n{r['body'][:4000]}" for r in [*samples, *sent]
    )
    voice = brain.ask(
        "Study these writing samples and describe the author's voice so another writer could "
        "imitate it closely. Quote real phrases they use.\n\n"
        f"About them:\n{_about(conn)}\n\nSamples:\n{text}",
        VOICE_SCHEMA,
    )
    voice = {k: [clean(x) for x in v] if isinstance(v, list) else clean(v) for k, v in voice.items()}
    db.set_profile(conn, "voice", voice)
    return voice


def recap(conn: sqlite3.Connection, brain: Brain, day_rows: dict, now: datetime | None = None) -> dict:
    """The day's recap. "For tomorrow" points at open todos by id (never a reworded copy of one, which
    "+ todo" would duplicate); a new idea only when nothing open fits. Written before the evening, it's
    a recap so far: nothing still to come today counts as slipped."""
    about = db.get_profile(conn, "about", {})
    nudge = about.get("nudge") or "warm and encouraging"
    now = now or datetime.now().astimezone()
    today = clock.today(now)

    def when(t: dict) -> str:
        if not t.get("due_at"):
            return ""
        due = clock.local(t["due_at"])
        return (
            f", due {'today' if clock.day_of(t['due_at']) == today else due.strftime('%a %d %b')} {due:%H:%M}"
        )

    def added_today(t: dict) -> str:
        return ", added today" if clock.day_of(t["created_at"]) == today else ""

    lines = [f"[log] {e['body']}" for e in day_rows["log"]]
    lines += [f"[done] {t['title']}" for t in day_rows["done"]]
    lines += [f"[open #{t['id']}{when(t)}{added_today(t)}] {t['title']}" for t in day_rows["open"]]
    # more than an hour before bedtime: the day isn't over, so this is a recap so far
    early = now < clock.at_on(today, get_settings().day.bed_at) - timedelta(hours=1)
    r = brain.ask(
        f"You are a small desk companion. Write the user's recap of today, in a {nudge} tone. It is {now:%H:%M}"
        + (", so the day isn't over: recap it so far, and don't call anything due later today or added today "
           "missed or untouched. " if early else ". ")
        + "Be specific about what they did and gentle about what slipped. For tomorrow, pick at most three of "
        "their open todos by number (todo = the number, text = its title as written); only if nothing open fits, "
        "suggest one new small thing with todo 0. Never suggest anything already done. No em dashes, no "
        f"therapy-speak.\n\nAbout them:\n{_about(conn)}\n\nToday:\n" + "\n".join(lines),
        RECAP_SCHEMA,
    )  # fmt: skip
    titles = {t["id"]: t["title"] for t in day_rows["open"]}
    done = {d["title"].lower() for d in day_rows["done"]}
    picks = []

    def words(s: str) -> set[str]:
        return {w for w in re.findall(r"\w+", s.lower()) if len(w) > 2}

    for x in r["tomorrow"]:
        tid = x.get("todo") if x.get("todo") in titles else None
        # a "new idea" that names an open todo ("Knock out Tiktok setup") is that todo
        tid = tid or next(
            (i for i, ti in titles.items() if words(ti) and words(ti) <= words(x.get("text", ""))), None
        )
        text = titles[tid] if tid else clean(x.get("text", ""))
        if text and text.lower() not in done and all(p["text"] != text for p in picks):
            picks.append({"text": text, "todo_id": tid})
    return {"headline": clean(r["headline"]), "recap": clean(r["recap"]), "tomorrow": picks, "so_far": early}
