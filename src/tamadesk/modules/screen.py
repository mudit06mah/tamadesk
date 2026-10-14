"""Is this a place the user would want to work (or sell to)? Checked against what they told us.

Preferences live in the profile (`about`): `avoid` (deal-breakers: "unpaid, crypto, gambling,
on-site only") and `wants` (what makes a place good: "small design-led teams, remote-friendly").
1. Free first: an avoid word in the posting drops it, with the word as the reason.
2. Then one light, capped model call for the companies the words can't decide, a batch at a time,
   through whichever brain the user chose (Claude's light model or a local Ollama model).
3. Each verdict is cached per company, so a company is judged once (again only if the preferences
   change). No preferences: nothing is screened and nothing is spent.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3

from tamadesk.brain import Brain, BrainError

BATCH = 12  # companies per call; the rest wait for the next refresh
SCHEMA = {"type": "object", "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "required": ["company", "ok", "why"],
    "properties": {"company": {"type": "string"}, "ok": {"type": "boolean"},
                   "why": {"type": "string", "description": "under 12 words"}}}}}}  # fmt: skip


def prefs(about: dict) -> tuple[list[str], str]:
    """(deal-breakers, what they want) from the user's about answers."""
    avoid = [w.strip().lower() for w in re.split(r",|;|\n", about.get("avoid", "")) if w.strip()]
    return avoid, about.get("wants", "").strip()


def _sig(avoid: list[str], wants: str) -> str:
    return hashlib.sha1(f"{sorted(avoid)}|{wants}".encode()).hexdigest()[:12]


def key(company: str) -> str:
    """A company name normalized for caching ('Acme, Inc.' -> 'acmeinc')."""
    return re.sub(r"[^a-z0-9]", "", company.lower())[:60]


def rule(text: str, avoid: list[str]) -> str | None:
    """The first deal-breaker the text mentions, or None. 'on-site only' also matches 'onsite only'."""
    t = text.lower()
    for a in avoid:
        words = [re.escape(w) for w in re.findall(r"[\w+#]+", a)]
        if words and re.search(r"\b" + r"[\s-]*".join(words) + r"\b", t):
            return a
    return None


def screen(
    conn: sqlite3.Connection, about: dict, candidates: list[dict], brain: Brain | None
) -> dict[str, tuple[bool, str]]:
    """{company key: (ok, why)} for the candidates' companies. candidates: [{company, text}]."""
    avoid, wants = prefs(about)
    if not avoid and not wants:
        return {}
    sig = _sig(avoid, wants)
    out: dict[str, tuple[bool, str]] = {}
    unknown: dict[str, dict] = {}
    for c in candidates:
        k = key(c["company"])
        if not k or k in out:
            continue
        if hit := rule(c["text"], avoid):
            out[k] = (False, f"mentions {hit}")
            continue
        row = conn.execute("SELECT ok, why, prefs FROM companies WHERE key = ?", (k,)).fetchone()
        if row and row["prefs"] == sig:
            out[k] = (bool(row["ok"]), row["why"] or "")
        else:
            unknown.setdefault(k, c)
    if unknown and brain is not None:
        batch = list(unknown.items())[:BATCH]
        listing = "\n".join(f"- {c['company']}: {c['text'][:300]}" for _, c in batch)
        prompt = ("Would this person want to work with each company below? Judge only against their stated "
                  "preferences; if a company says too little to tell, say ok.\n"
                  f"Avoid: {', '.join(avoid) or '(nothing stated)'}\nWants: {wants or '(nothing stated)'}\n\n{listing}")  # fmt: skip
        try:
            got = brain.ask(prompt, SCHEMA, light=True, kind="screen")["verdicts"]
        except (BrainError, KeyError, TypeError):
            got = []  # budget spent or the model failed: leave them unscreened this time
        by_name = {key(v.get("company", "")): v for v in got if isinstance(v, dict)}
        for k, c in batch:
            if (v := by_name.get(k)) is not None:
                out[k] = (bool(v.get("ok", True)), str(v.get("why", ""))[:120])
                conn.execute(
                    "INSERT OR REPLACE INTO companies (key, ok, why, prefs) VALUES (?, ?, ?, ?)",
                    (k, int(out[k][0]), out[k][1], sig),
                )
    return out
