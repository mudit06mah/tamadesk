"""Module spec: validation, YAML files on disk, templates, and schedule parsing."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from tamadesk.core.config import Settings
from tamadesk.modules.fit import Fit

TEMPLATES = Path(__file__).parent / "templates"
Action = Literal["save", "skip", "open", "summarize", "todo", "done", "draft"]
SCHEDULE_RE = re.compile(r"^(?:(\d+)([mhd])|daily (\d{1,2}):(\d{2}))$")


class Source(BaseModel, extra="allow"):
    """One source of a tab: its `type` plus that source's own params."""

    type: str  # a key of sources.SOURCES; the rest of the fields are that source's params

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, v):
        # the assistant's search tool takes {type, params: {...}}; tabs take the params inline
        if isinstance(v, dict) and isinstance(v.get("params"), dict):
            v = {k: x for k, x in v.items() if k != "params"} | v["params"]
        return v

    @model_validator(mode="after")
    def _known(self):
        from tamadesk.modules.sources import SOURCES

        fn = SOURCES.get(self.type)
        if fn is None:
            raise ValueError(f"unknown source type {self.type!r}; use one of {', '.join(sorted(SOURCES))}")
        params = inspect.signature(fn).parameters
        if any(p.kind is p.VAR_KEYWORD for p in params.values()):
            return self
        allowed = set(params)
        if bad := set(self.model_extra or {}) - allowed:
            raise ValueError(
                f"{self.type} doesn't take {', '.join(sorted(bad))}; it takes {', '.join(sorted(allowed))}"
            )
        return self


class Workflow(BaseModel):
    """A one-click 'do something with what I kept' for a tab: the prompt goes to the assistant along
    with the kept items."""

    label: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=5, max_length=1000)


class Module(BaseModel):
    """A tab: where its items come from, how they're filtered and ranked, and what you can do with them. Saved as
    YAML."""

    id: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    name: str = Field(min_length=1, max_length=24)
    icon: str = "star"
    every: str = "6h"  # 30m | 6h | 7d | daily 08:00
    sources: list[Source] = Field(min_length=1, max_length=8)
    interests: list[str] = []  # words that rank items up from day one
    # what every item must be about: at least one of these words or phrases ("Starlink", "Elon Musk");
    # anything else is dropped as off topic, free. Empty: no check.
    match: list[str] = Field(default=[], max_length=20)
    actions: list[Action] = ["save", "skip", "open"]
    keep: int = Field(default=150, ge=10, le=1000)  # most unseen items kept per module
    notify: bool = False  # a desktop notification when a refresh brings something new
    workflows: list[Workflow] = Field(default=[], max_length=4)
    fit: Fit | None = None  # drop items that don't match what the user is after (level, role)
    expire_days: int = Field(default=14, ge=1, le=365)  # unseen items older than this quietly go
    # job search that learns (all off by default; the jobs template turns them on)
    watch_boards: bool = False  # read the company job boards that search results came from, on every refresh
    verify: bool = False  # open each posting found by search and drop closed ones
    max_age_days: int | None = Field(default=None, ge=1, le=365)  # drop postings older than this
    screen: bool = False  # check new companies against the user's preferences (about: avoid, wants)
    # feed: ranked by taste. steps: a path in order (items carry data.step and data.topic, e.g. a roadmap)
    layout: Literal["feed", "steps"] = "feed"

    @field_validator("every")
    @classmethod
    def _every(cls, v: str) -> str:
        if not SCHEDULE_RE.match(v.strip()):
            raise ValueError("use 30m, 6h, 7d or 'daily 08:00'")
        return v.strip()

    @model_validator(mode="after")
    def _a_path_stays(self):
        if self.layout == "steps":  # a learning path isn't news: nothing in it expires
            self.expire_days = 365
        return self

    @model_validator(mode="after")
    def _agent_not_too_often(self):
        # an agent source is a Claude run on every refresh: no faster than every 6 hours
        kind, kw = trigger(self.every)
        if any(x.type == "agent" for x in self.sources) and kind == "interval" and kw.get("minutes", 0) + \
                kw.get("hours", 0) * 60 < 360 and "days" not in kw:  # fmt: skip
            raise ValueError(
                "tabs with an 'agent' source can refresh at most every 6h (it costs tokens each time)"
            )
        return self


def trigger(every: str) -> tuple[str, dict]:
    """APScheduler (trigger, kwargs) for a schedule string."""
    m = SCHEDULE_RE.match(every)
    if m[1]:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[m[2]]
        return "interval", {unit: int(m[1])}
    return "cron", {"hour": int(m[3]), "minute": int(m[4])}


def module_dir(s: Settings) -> Path:
    """The folder of tab YAML files."""
    d = s.home / "modules"
    d.mkdir(exist_ok=True)
    return d


def load_all(s: Settings) -> list[Module]:
    """Every tab on disk (broken files are skipped)."""
    out = []
    for p in sorted(module_dir(s).glob("*.yaml")):
        try:
            out.append(Module(**yaml.safe_load(p.read_text())))
        except Exception:  # noqa: BLE001, S112 - a broken hand-edited file must not take the app down
            continue
    return out


def get(s: Settings, module_id: str) -> Module | None:
    """One tab by id."""
    p = module_dir(s) / f"{module_id}.yaml"
    return Module(**yaml.safe_load(p.read_text())) if p.is_file() else None


def save(s: Settings, m: Module) -> Module:
    """Write a tab's YAML (defaults left out, so files stay short)."""
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
    """Remove a tab's YAML."""
    (module_dir(s) / f"{module_id}.yaml").unlink(missing_ok=True)


def slug(name: str) -> str:
    """An id for a tab name: 'UI/UX Jobs' -> 'ui-ux-jobs'."""
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


def _drop_blank(src: dict) -> dict | None:
    """A blank optional param is left out (the source's default applies); a blank required one means the
    source can't run, so it's dropped (e.g. "Companies to watch" left empty)."""
    from tamadesk.modules.sources import SOURCES

    fn = SOURCES.get(src.get("type", ""))
    params = inspect.signature(fn).parameters if fn else {}
    out = {}
    for k, v in src.items():
        if v != "":
            out[k] = v
        elif k not in params or params[k].default is inspect.Parameter.empty:
            return None
    return out


def from_template(
    key: str, params: dict[str, str], name: str | None = None, about: dict | None = None
) -> Module:
    """A tab from a template. A blank param marked `from: level|roles|location` is filled from what
    the user said they're after (New Game or Bolt), so they don't type it twice."""
    from tamadesk.modules import fit

    t = next((t for t in templates() if t["key"] == key), None)
    if t is None:
        raise ValueError(f"unknown template {key!r}")
    known = fit.profile(about or {})
    values = {k: (params.get(k) or known.get(p.get("from", "")) or p.get("default", "") or "").strip()
              for k, p in t.get("params", {}).items()}  # fmt: skip
    spec = _fill(t["module"], values)
    # comma-separated params become lists where the template asks for a list (interests, feeds)
    spec["interests"] = [w.strip() for x in spec.get("interests", []) for w in x.split(",") if w.strip()]
    spec["match"] = [w.strip() for x in spec.get("match", []) for w in x.split(",") if w.strip()]
    # an optional param left blank drops the source that needed it (e.g. "extra RSS feed")
    spec["sources"] = [x for x in (_drop_blank(x) for x in spec["sources"]) if x is not None]
    for src in spec["sources"]:  # "${level} ${role}" with no level leaves a stray space
        src.update(
            {k: re.sub(r"[ \t]+", " ", v).strip() for k, v in src.items() if isinstance(v, str)}
        )  # lines stay
    if spec.get("fit") and not any(spec["fit"].values()):
        spec.pop("fit")
    name = name or spec["name"]
    return Module(**spec | {"name": name, "id": slug(name)})
