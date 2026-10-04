"""What the light brain writes outside the assistant: the voice profile and the evening recap.

The voice profile is built once from the user's own writing samples, then reused, so drafts sound
like the user and not like a chatbot.
"""

from __future__ import annotations

import re
import sqlite3

from tamadesk.brain import Brain
from tamadesk.core import db

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
        "tomorrow": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["headline", "recap", "tomorrow"],
}


def clean(text: str) -> str:
    """Deterministic last pass: models love em dashes even when told not to."""
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", text)


def _about(conn: sqlite3.Connection) -> str:
    about = db.get_profile(conn, "about", {})
    return "\n".join(f"- {k}: {v}" for k, v in about.items() if v)


def build_voice(conn: sqlite3.Connection, brain: Brain) -> dict:
    samples = conn.execute("SELECT kind, title, body FROM samples ORDER BY id").fetchall()
    if not samples:
        raise ValueError("add at least one writing sample first")
    text = "\n\n".join(f"### {r['kind']}: {r['title'] or 'untitled'}\n{r['body'][:4000]}" for r in samples)
    voice = brain.ask(
        "Study these writing samples and describe the author's voice so another writer could "
        "imitate it closely. Quote real phrases they use.\n\n"
        f"About them:\n{_about(conn)}\n\nSamples:\n{text}",
        VOICE_SCHEMA,
    )
    db.set_profile(conn, "voice", voice)
    return voice


def recap(conn: sqlite3.Connection, brain: Brain, day_rows: dict) -> dict:
    about = db.get_profile(conn, "about", {})
    nudge = about.get("nudge") or "warm and encouraging"
    lines = [f"[log] {e['body']}" for e in day_rows["log"]]
    lines += [f"[done] {t['title']}" for t in day_rows["done"]]
    lines += [f"[still open] {t['title']}" for t in day_rows["open"]]
    r = brain.ask(
        f"You are a small desk companion. Write tonight's recap of the user's day, in a {nudge} tone. "
        "Be specific about what they did, gentle about what slipped, and suggest at most three "
        "small things for tomorrow (prefer open todos). No em dashes, no therapy-speak.\n\n"
        f"About them:\n{_about(conn)}\n\nToday:\n" + "\n".join(lines),
        RECAP_SCHEMA,
    )
    return {
        "headline": clean(r["headline"]),
        "recap": clean(r["recap"]),
        "tomorrow": [clean(t) for t in r["tomorrow"]],
    }
