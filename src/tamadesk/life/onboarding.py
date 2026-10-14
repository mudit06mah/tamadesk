"""The "New Game" questions. Answers land in profile['about'] and shape every draft and recap.

A first game asks only the `core` ones (who you are, what you're up to, what you're after); the rest
are in Settings (and Bolt asks when it needs one), or all at once when New Game is replayed."""

from __future__ import annotations

QUESTIONS: list[dict] = [
    {
        "key": "name",
        "q": "What should your companion call you?",
        "hint": "first name or a nickname",
        "core": True,
    },
    {
        "key": "doing",
        "q": "What are you up to these days?",
        "hint": "studying, a job, building something, job hunting…",
        "options": ["studying ", "working as a ", "building something: ", "freelancing as a ", "job hunting"],
        "core": True,
    },
    {
        "key": "looking_for",
        "q": "Looking for work right now? What kind?",
        "hint": "e.g. an internship in UI/UX design, first job as a backend dev, not now",
        "options": [
            "not now",
            "an internship in ",
            "my first job as ",
            "a mid-level role in ",
            "a senior role in ",
        ],
        "core": True,
    },
    {
        "key": "avoid",
        "q": "Anything about work you'd rather avoid?",
        "hint": "e.g. unpaid, crypto, gambling, on-site only, huge agencies (job searches skip these)",
    },
    {
        "key": "wants",
        "q": "What makes a place good for you?",
        "hint": "e.g. small design-led teams, remote-friendly, mentorship, products people love",
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
