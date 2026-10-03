"""'Make me a tab': turn a sentence into a module by picking a template and filling its fields.

The brain only chooses among templates and writes a few short strings (light model, ~100 output
tokens). The YAML itself is built deterministically and validated, so a bad answer can't break
the app or invent a source.
"""

from __future__ import annotations

from tamadesk.brain import Brain
from tamadesk.modules.spec import Module, from_template, templates

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "template": {"type": "string"},
        "name": {"type": "string", "description": "short tab name, 1-2 words"},
        "params": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["template", "name", "params"],
}


def catalog() -> str:
    return "\n".join(
        f"- {t['key']}: {t['blurb']} params: "
        + ", ".join(f"{k} ({p['label']})" for k, p in t.get("params", {}).items())
        for t in templates()
    )


def from_sentence(brain: Brain, wish: str, about: str = "") -> Module:
    out = brain.ask(
        "Pick the one template that best fits the user's wish and fill its params with short, "
        "specific values (search queries, comma-separated topics). Use only the listed template keys.\n\n"
        f"Templates:\n{catalog()}\n\nAbout the user: {about}\nWish: {wish}",
        PICK_SCHEMA,
        light=True,
    )
    return from_template(out["template"], out.get("params", {}), out.get("name") or None)
