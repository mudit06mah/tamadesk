"""The "New Game" questions. Answers land in profile['about'] and shape every draft and recap."""

from __future__ import annotations

QUESTIONS: list[dict] = [
    {"key": "name", "q": "What should your companion call you?", "hint": "first name or a nickname"},
    {
        "key": "doing",
        "q": "What are you up to these days?",
        "hint": "studying, a job, building something, job hunting…",
    },
    {
        "key": "goals",
        "q": "What do you want to get done in the next few months?",
        "hint": "one or two big things",
    },
    {
        "key": "stuck",
        "q": "What usually gets in your way?",
        "hint": "procrastination, too many tabs, mornings…",
    },
    {
        "key": "voice",
        "q": "How do you like to write to people?",
        "hint": "casual, short, lowercase, lots of emojis, formal…",
    },
    {
        "key": "never",
        "q": "Anything your drafts should never do?",
        "hint": "e.g. no 'I hope this finds you well'",
    },
    {
        "key": "nudge",
        "q": "How should your companion nudge you?",
        "hint": "gentle, hype-man, strict coach, deadpan…",
    },
]

COMPANIONS: list[dict] = [
    {"species": "blob", "label": "Blob", "blurb": "Squishy, patient, cheers for tiny wins."},
    {"species": "sprout", "label": "Sprout", "blurb": "Grows a leaf every streak day. Loves routines."},
    {"species": "bot", "label": "Bolt", "blurb": "A tiny robot. Precise, a bit dramatic about deadlines."},
]
