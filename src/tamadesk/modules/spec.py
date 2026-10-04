"""Module spec: validation, YAML files on disk, templates, and schedule parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from tamadesk.core.config import Settings

TEMPLATES = Path(__file__).parent / "templates"
View = Literal["feed", "deck"]
Action = Literal["save", "skip", "open", "summarize", "todo", "done", "draft"]
SCHEDULE_RE = re.compile(r"^(?:(\d+)([mhd])|daily (\d{1,2}):(\d{2}))$")


class Source(BaseModel, extra="allow"):
    type: str  # a key of sources.SOURCES; the rest of the fields are that source's params


class Module(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    name: str = Field(min_length=1, max_length=24)
    icon: str = "star"
    view: View = "feed"
    every: str = "6h"  # 30m | 6h | 7d | daily 08:00
    sources: list[Source] = Field(min_length=1, max_length=8)
    interests: list[str] = []  # words that rank items up from day one
    actions: list[Action] = ["save", "skip", "open"]
    reasons: list[str] = []  # deck only: quick skip reasons
    keep: int = Field(default=150, ge=10, le=1000)  # most unseen items kept per module

    @field_validator("every")
    @classmethod
    def _every(cls, v: str) -> str:
        if not SCHEDULE_RE.match(v.strip()):
            raise ValueError("use 30m, 6h, 7d or 'daily 08:00'")
        return v.strip()


def trigger(every: str) -> tuple[str, dict]:
    """APScheduler (trigger, kwargs) for a schedule string."""
    m = SCHEDULE_RE.match(every)
    if m[1]:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[m[2]]
        return "interval", {unit: int(m[1])}
    return "cron", {"hour": int(m[3]), "minute": int(m[4])}


def module_dir(s: Settings) -> Path:
    d = s.home / "modules"
    d.mkdir(exist_ok=True)
    return d


def load_all(s: Settings) -> list[Module]:
    out = []
    for p in sorted(module_dir(s).glob("*.yaml")):
        try:
            out.append(Module(**yaml.safe_load(p.read_text())))
        except Exception:  # noqa: BLE001, S112 - a broken hand-edited file must not take the app down
            continue
    return out


def get(s: Settings, module_id: str) -> Module | None:
    p = module_dir(s) / f"{module_id}.yaml"
    return Module(**yaml.safe_load(p.read_text())) if p.is_file() else None


def save(s: Settings, m: Module) -> Module:
    (module_dir(s) / f"{m.id}.yaml").write_text(
        yaml.safe_dump(m.model_dump(exclude_defaults=True), sort_keys=False)
    )
    return m


def create(s: Settings, m: Module) -> Module:
    """Save as a new tab, never overwriting one: 'papers' -> 'papers-2' if taken."""
    base, n = m.id, 2
    while (module_dir(s) / f"{m.id}.yaml").exists():
        m = m.model_copy(update={"id": f"{base[:29]}-{n}"})
        n += 1
    return save(s, m)


def delete(s: Settings, module_id: str) -> None:
    (module_dir(s) / f"{module_id}.yaml").unlink(missing_ok=True)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "tab"


# ---------------------------------------------------------------- templates


def templates() -> list[dict]:
    """[{key, title, blurb, params: {name: {label, default}}, module: {...}}], from templates/*.yaml."""
    return [{"key": p.stem, **yaml.safe_load(p.read_text())} for p in sorted(TEMPLATES.glob("*.yaml"))]


def _fill(v, params: dict[str, str]):
    if isinstance(v, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: params.get(m[1], ""), v)
    if isinstance(v, list):
        return [x for x in (_fill(x, params) for x in v) if x != ""]
    if isinstance(v, dict):
        return {k: _fill(x, params) for k, x in v.items()}
    return v


def from_template(key: str, params: dict[str, str], name: str | None = None) -> Module:
    t = next((t for t in templates() if t["key"] == key), None)
    if t is None:
        raise ValueError(f"unknown template {key!r}")
    values = {k: (params.get(k) or p.get("default", "")).strip() for k, p in t.get("params", {}).items()}
    spec = _fill(t["module"], values)
    # comma-separated params become lists where the template asks for a list (interests, feeds)
    spec["interests"] = [w.strip() for x in spec.get("interests", []) for w in x.split(",") if w.strip()]
    # an optional param left blank drops the source that needed it (e.g. "extra RSS feed")
    spec["sources"] = [x for x in spec["sources"] if all(v != "" for v in x.values())]
    name = name or spec["name"]
    return Module(**spec | {"name": name, "id": slug(name)})
