"""Modules API: tabs (create from a template or a sentence, edit, delete, run) and their items."""

from __future__ import annotations

import json

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from tamadesk.api import jobs
from tamadesk.api.routes import Conn, _brain_call
from tamadesk.brain import get_brain
from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life.actions import add_todo
from tamadesk.modules import engine, spec

router = APIRouter(prefix="/api")


def _module_or_404(module_id: str) -> spec.Module:
    m = spec.get(get_settings(), module_id)
    if m is None:
        raise HTTPException(404, "no such tab")
    return m


def _install(m: spec.Module) -> dict:
    """Save a new tab, schedule it, and fill it right away."""
    s = get_settings()
    m = spec.create(s, m)
    jobs.sync_modules(s)
    jobs.run_now(m.id)
    return m.model_dump()


def install_templates(picks: list[dict]) -> list[str]:
    """Used by New Game: [{template, params}] -> created tab ids."""
    return [_install(spec.from_template(p["template"], p.get("params", {})))["id"] for p in picks]


@router.get("/modules")
def list_modules(conn: Conn) -> list[dict]:
    counts = {(r["module"], r["status"]): r["n"] for r in conn.execute(
        "SELECT module, status, count(*) AS n FROM items GROUP BY module, status")}  # fmt: skip
    runs = {r["module"]: dict(r) for r in conn.execute("SELECT * FROM module_runs")}
    hidden = db.get_profile(conn, "dismissed_errors", {})
    for r in runs.values():  # an error the user dismissed stays hidden until it changes
        if r["last_error"] and hidden.get(r["module"]) == r["last_error"]:
            r["last_error"] = None
    return [m.model_dump() | {"new": counts.get((m.id, "new"), 0), "saved": counts.get((m.id, "saved"), 0),
                              "run": runs.get(m.id)} for m in spec.load_all(get_settings())]  # fmt: skip


@router.post("/modules/{module_id}/dismiss")
def dismiss_error(module_id: str, conn: Conn) -> dict:
    row = conn.execute("SELECT last_error FROM module_runs WHERE module = ?", (module_id,)).fetchone()
    if row and row["last_error"]:
        db.set_profile(
            conn,
            "dismissed_errors",
            db.get_profile(conn, "dismissed_errors", {}) | {module_id: row["last_error"]},
        )
    return {"ok": True}


@router.get("/templates")
def list_templates() -> list[dict]:
    return [{k: t[k] for k in ("key", "title", "blurb", "icon")} | {"params": t.get("params", {})}
            for t in spec.templates()]  # fmt: skip


class FromTemplate(BaseModel):
    template: str
    params: dict[str, str] = {}
    name: str | None = None


@router.post("/modules")
def create_module(body: FromTemplate) -> dict:
    try:
        return _install(spec.from_template(body.template, body.params, body.name))
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, str(e)) from e


@router.post("/modules/spec")
def create_from_spec(body: dict) -> dict:
    """A full module spec (the assistant's create_tab tool posts here)."""
    try:
        return _install(spec.Module(**body))
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/modules/{module_id}/yaml")
def module_yaml(module_id: str) -> dict:
    return {
        "yaml": yaml.safe_dump(_module_or_404(module_id).model_dump(exclude_defaults=True), sort_keys=False)
    }


class YamlIn(BaseModel):
    yaml: str


@router.put("/modules/{module_id}")
def edit_module(module_id: str, body: YamlIn, conn: Conn) -> dict:
    """Hand-edit a tab's YAML. Validated before saving; the id stays the same."""
    _module_or_404(module_id)
    try:
        m = spec.Module(**(yaml.safe_load(body.yaml) or {}) | {"id": module_id})
    except (yaml.YAMLError, ValidationError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    return _replace(conn, m)


@router.put("/modules/{module_id}/spec")
def replace_spec(module_id: str, body: dict, conn: Conn) -> dict:
    """A full module spec for an existing tab (the assistant's update_tab tool puts here)."""
    _module_or_404(module_id)
    try:
        return _replace(conn, spec.Module(**body | {"id": module_id}))
    except ValidationError as e:
        raise HTTPException(422, str(e)) from e


def _replace(conn, m: spec.Module) -> dict:
    """Save a changed tab: old errors are cleared, it's re-ranked, rescheduled and refreshed now."""
    s = get_settings()
    spec.save(s, m)
    conn.execute("UPDATE module_runs SET last_error = NULL WHERE module = ?", (m.id,))
    engine.rescore(conn, m)
    jobs.sync_modules(s)
    jobs.run_now(m.id)
    return m.model_dump()


@router.delete("/modules/{module_id}")
def delete_module(module_id: str, conn: Conn) -> dict:
    s = get_settings()
    spec.delete(s, module_id)
    for table in ("items", "terms", "module_runs"):
        conn.execute(f"DELETE FROM {table} WHERE module = ?", (module_id,))
    jobs.sync_modules(s)
    return {"ok": True}


@router.post("/modules/{module_id}/run")
def run_module(module_id: str) -> dict:
    _module_or_404(module_id)
    jobs.run_now(module_id)
    return {"ok": True}


def _item_view(r) -> dict:
    return dict(r) | {"data": json.loads(r["data"] or "{}"), "why": json.loads(r["why"] or "[]")}


@router.get("/modules/{module_id}/items")
def items(module_id: str, conn: Conn, status: str = "new", offset: int = 0, limit: int = 30) -> dict:
    order = "score DESC, id DESC" if status == "new" else "decided_at DESC"
    rows = conn.execute(
        f"SELECT * FROM items WHERE module = ? AND status = ? ORDER BY {order} LIMIT ? OFFSET ?",
        (module_id, status, limit + 1, offset),
    ).fetchall()
    return {"items": [_item_view(r) for r in rows[:limit]], "has_more": len(rows) > limit}


class ActIn(BaseModel):
    reason: str = ""


@router.post("/items/{item_id}/todo")
def item_to_todo(item_id: int, conn: Conn) -> dict:
    it = conn.execute("SELECT title, url FROM items WHERE id = ?", (item_id,)).fetchone()
    if it is None:
        raise HTTPException(404, "no such item")
    with db.transaction(conn):
        tid = add_todo(conn, f"{it['title'][:120]} {it['url'] or ''}".strip())
    return {"todo_id": tid}


@router.post("/items/{item_id}/summarize")
def item_summary(item_id: int, conn: Conn) -> dict:
    about = "; ".join(
        f"{k}: {v}" for k, v in db.get_profile(conn, "about", {}).items() if v and k in ("doing", "goals")
    )
    return _brain_call(lambda: engine.summarize(conn, get_brain(get_settings()), item_id, about))


@router.post("/items/{item_id}/{action}")
def item_action(item_id: int, action: str, body: ActIn, conn: Conn) -> dict:
    if action not in (*engine.STATUS, "undo"):
        raise HTTPException(404, "unknown action")
    try:
        r = engine.act(conn, item_id, action, reason=body.reason)
    except KeyError as e:
        raise HTTPException(404, "no such item") from e
    if action in ("save", "skip"):  # the taste model just learned: re-rank what's still unseen
        module = conn.execute("SELECT module FROM items WHERE id = ?", (item_id,)).fetchone()["module"]
        if m := spec.get(get_settings(), module):
            engine.rescore(conn, m)
    return r
