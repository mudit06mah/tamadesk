"""Your profile card: who you are on one short page, so Bolt knows you without rereading your resume.

- Written in the background when you add a resume: one light call through whichever brain you chose
  (Claude's light model or a local Ollama model), capped like every call.
- Kept as markdown in the memory folder (`memory/profile.md`). That file is the source of truth: edit
  it freely, in Settings or any editor. Every ask reads it.
- Links come out of the resume by plain regex, so the model can't drop or invent them, and a line
  with a number the resume doesn't have is dropped (models round "20 readers" up to "20+ users").
- Empty "about" answers (level, roles, location) are filled from it; your own words, including what
  you said you're looking for, always win.
- A rebuild replaces the resume part and keeps your Notes, where things you tell Bolt to remember land.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from tamadesk.brain import Brain
from tamadesk.core import db
from tamadesk.core.config import Settings
from tamadesk.life import memory
from tamadesk.modules import fit

FILE = "profile.md"
NOTES = "## Notes"
PROMPT_CHARS = 2000  # how much of the card rides along with every ask
RESUME_CHARS = 12_000
LIST = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "required": ["headline", "level", "roles", "location", "skills", "experience", "projects", "education", "wins"],
    "properties": {
        "headline": {"type": "string", "description": "one line: who they are now, in plain words"},
        "level": {"enum": ["internship", "junior", "mid", "senior", "unknown"],
                  "description": "the level of role they'd apply for next"},
        "roles": LIST | {"description": "2-4 job titles they'd apply for, lowercase"},
        "location": {"type": "string", "description": "city/country, and 'remote' if they say so; '' if not given"},
        "skills": LIST | {"description": "up to 12, strongest first, as they're named in the resume"},
        "experience": LIST | {"description": "up to 4: 'Role, Org (years): what they did, with a number if given'"},
        "projects": LIST | {"description": "up to 4: 'Name: what it is and what they did'"},
        "education": {"type": "string", "description": "one line, '' if not given"},
        "wins": LIST | {"description": "up to 3 concrete things worth mentioning in an email to a company"},
    },
}  # fmt: skip
URL = re.compile(
    r"(?i:(?:https?://|www\.)[^\s<>()\"',;]+"  # written out in full
    r"|\b(?:github\.com|gitlab\.com|linkedin\.com/in|behance\.net|dribbble\.com|medium\.com)/[\w.@\-/]+)"
    # a bare personal site ('robin.design', 'robin.github.io/work'); lowercase, so 'ASP.NET' isn't one
    r"|(?<![@\w.-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:github\.io|com|dev|design|me|co|net|org|site|page|art|studio|xyz"
    r"|app|example)(?:/[^\s<>()\"',;]*)?(?![\w@-])"
)


def path(s: Settings) -> Path:
    return memory.memory_dir(s) / FILE


def read(s: Settings) -> str:
    p = path(s)
    return p.read_text() if p.exists() else ""


def save(s: Settings, text: str) -> None:
    path(s).write_text(text.strip() + "\n")


def notes(text: str) -> str:
    """The Notes section's body: the user's own part of the card."""
    _, found, rest = text.partition(NOTES)
    return re.split(r"^## ", rest, maxsplit=1, flags=re.MULTILINE)[0].strip() if found else ""


def links(text: str) -> list[str]:
    """Every link in the resume, as written, minus mail addresses. PDFs often drop the https://."""
    out: list[str] = []
    for m in URL.finditer(text):
        url = m.group(0).rstrip(".")
        url = url if url.lower().startswith("http") else f"https://{url}"
        if "@" not in url.split("/", 3)[2] and url.lower() not in (u.lower() for u in out):
            out.append(url)
    return out[:8]


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _clean(xs: list[str], n: int, resume: str | None = None, head: bool = False) -> list[str]:
    """Non-empty lines, at most n. With the resume, a line with a number it doesn't have is dropped, or
    with `head`, cut back to the part before its colon ('Role, Org (years)') if that part holds up."""
    have = set(NUMBER.findall(resume)) if resume is not None else None
    out = []
    for x in (x.strip() for x in xs if isinstance(x, str) and x.strip()):
        if have is not None and not set(NUMBER.findall(x)) <= have:
            x = x.split(":", 1)[0].strip() if head and ":" in x else ""
            if not x or not set(NUMBER.findall(x)) <= have:
                continue
        out.append(x)
    return out[:n]


def render(card: dict, resume_text: str, source: str, kept_notes: str, day: date | None = None) -> str:
    """The card's markdown from the model's answer, keeping only what the resume backs up, plus the user's Notes."""
    level = card.get("level") if card.get("level") != "unknown" else ""
    after = " · ".join(
        x for x in [level, ", ".join(_clean(card.get("roles", []), 4)), card.get("location", "")] if x
    )
    lines = [
        "# Profile card",
        "",
        f"Written from {source} on {(day or datetime.now().astimezone().date()).isoformat()}. Edit anything; a rebuild keeps your Notes.",
        "",
        f"**Who:** {card.get('headline', '').strip()}",
    ]
    if after:
        lines.append(f"**Looking for:** {after}")
    if card.get("education", "").strip():
        lines.append(f"**Education:** {card['education'].strip()}")
    sections = [("Skills", [", ".join(_clean(card.get("skills", []), 12))]),
                ("Experience", [f"- {x}" for x in _clean(card.get("experience", []), 4, resume_text, head=True)]),
                ("Projects", [f"- {x}" for x in _clean(card.get("projects", []), 4, resume_text, head=True)]),
                ("Worth mentioning", [f"- {x}" for x in _clean(card.get("wins", []), 3, resume_text)]),
                ("Links", [f"- {u}" for u in links(resume_text)])]  # fmt: skip
    for title, body in sections:
        if any(b.strip("- ") for b in body):
            lines += ["", f"## {title}", *body]
    lines += ["", NOTES, kept_notes] if kept_notes else ["", NOTES]
    return "\n".join(lines).strip() + "\n"


def resume(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The newest resume, if any."""
    return conn.execute("SELECT name, text FROM docs WHERE kind = 'resume' ORDER BY id DESC").fetchone()


def build(s: Settings, conn: sqlite3.Connection, brain: Brain) -> str | None:
    """Write the card from the newest resume. None when there's no resume to read."""
    doc = resume(conn)
    if doc is None:
        return None
    card = brain.ask(
        "Here is a person's resume. Write a short profile card of them for their personal assistant, who uses "
        "it to search for jobs that fit and to write emails in their name. Use only what the resume says; "
        "never guess or embellish: copy numbers and qualifiers (like 'basic') exactly, never round up or add "
        "'+'. Short lines.\n\nResume:\n" + doc["text"][:RESUME_CHARS],
        SCHEMA, light=True, kind="profile",
    )  # fmt: skip
    text = render(card, doc["text"], doc["name"], notes(read(s)))
    save(s, text)
    fill_about(conn, card)
    return text


def fill_about(conn: sqlite3.Connection, card: dict) -> list[str]:
    """Fill the about answers that are still empty; never touch one the user wrote. "Looking for a design
    internship" already answers level and roles, so those stay theirs."""
    about = db.get_profile(conn, "about", {})
    mine = fit.profile(about)
    found = {"level": card.get("level") if card.get("level") != "unknown" else "",
             "roles": ", ".join(_clean(card.get("roles", []), 4)), "location": card.get("location", "").strip()}  # fmt: skip
    filled = [k for k, v in found.items() if v and not mine.get(k)]
    if filled:
        db.set_profile(conn, "about", about | {k: found[k] for k in filled})
    return filled


def for_prompt(s: Settings) -> str:
    """The card without its title and 'written from' line, capped, for Bolt's prompt."""
    lines = read(s).strip().splitlines()
    while lines and (
        lines[0].startswith("# ") or lines[0].startswith("Written from ") or not lines[0].strip()
    ):
        lines.pop(0)
    body = "\n".join(lines).replace(f"{NOTES}\n", "## Notes (things they asked you to remember)\n")
    body = body.removesuffix(NOTES).strip()
    return body[:PROMPT_CHARS]


def add_note(s: Settings, text: str) -> None:
    """Something to remember about the user, kept under Notes (a card is started if there's none)."""
    line = "- " + " ".join(text.split())[:300]
    current = read(s).strip() or "# Profile card"
    head, found, rest = current.partition(NOTES)
    if not found:
        return save(s, f"{current}\n\n{NOTES}\n{line}")
    body, more, after = rest.partition("\n## ")  # sections the user added below Notes stay put
    kept = body.strip()
    save(s, f"{head}{NOTES}\n" + (f"{kept}\n" if kept else "") + line + (f"\n\n## {after}" if more else ""))
