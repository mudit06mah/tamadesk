"""JSON API for the desk: state, quick capture, todos, reminders, log, samples, drafts, recap."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from tamadesk.brain import BrainError, get_brain
from tamadesk.core import db
from tamadesk.core.config import get_settings, save_settings
from tamadesk.life import actions, capture, docs, game, github, writer
from tamadesk.life.onboarding import COMPANIONS, QUESTIONS

router = APIRouter(prefix="/api")


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def day_start_utc() -> str:
    """Local midnight today, as a SQLite UTC timestamp."""
    local_midnight = datetime.combine(datetime.now(UTC).astimezone().date(), time()).astimezone()
    return capture.sql_ts(local_midnight.astimezone(UTC).replace(tzinfo=None))


def today_rows(conn: sqlite3.Connection) -> dict:
    start = day_start_utc()
    q = conn.execute
    return {
        "open": [dict(r) for r in q("SELECT * FROM todos WHERE status = 'open' ORDER BY due_at IS NULL, due_at, id")],
        "done": [dict(r) for r in q("SELECT * FROM todos WHERE status = 'done' AND done_at >= ? ORDER BY done_at", (start,))],
        "log": [dict(r) for r in q("SELECT * FROM log_entries WHERE created_at >= ? ORDER BY id", (start,))],
    }  # fmt: skip


def _brain_call(fn):
    try:
        return fn()
    except BrainError as e:
        raise HTTPException(503 if e.kind in {"unavailable", "rate_limit"} else 502, str(e)) from e


# ---------------------------------------------------------------- state


@router.get("/state")
def state(conn: Conn) -> dict:
    s = get_settings()
    rows = today_rows(conn)
    q = conn.execute
    recap = q("SELECT detail, at FROM events WHERE kind = 'recap' AND at >= ? ORDER BY id DESC LIMIT 1",
              (day_start_utc(),)).fetchone()  # fmt: skip
    return {
        "onboarded": bool(db.get_profile(conn, "onboarded", False)),
        "about": db.get_profile(conn, "about", {}),
        "companion": db.get_profile(conn, "companion"),
        "has_voice": db.get_profile(conn, "voice") is not None,
        "samples": q("SELECT COUNT(*) FROM samples").fetchone()[0],
        "mail_drafts": q("SELECT COUNT(*) FROM drafts WHERE status = 'draft'").fetchone()[0],
        "brain": {"kind": s.brain.kind, "model": s.brain.model},
        "day": {"recap_hour": s.day.recap_hour, "todo_goal": s.day.todo_goal},
        "progress": game.progress(conn),
        "today": rows,
        "reminders": [dict(r) for r in q(
            "SELECT * FROM reminders WHERE status IN ('pending','fired') ORDER BY due_at LIMIT 20")],
        "recap": {"at": recap["at"], **json.loads(recap["detail"])} if recap else None,
        "activity": [dict(r) for r in q("SELECT kind, detail, xp, at FROM events ORDER BY id DESC LIMIT 15")],
    }  # fmt: skip


@router.get("/activity")
def activity(conn: Conn, offset: int = 0, limit: int = 30) -> dict:
    rows = conn.execute(
        "SELECT kind, detail, xp, at FROM events WHERE kind != 'recap' ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit + 1, offset),
    ).fetchall()
    return {"items": [dict(r) for r in rows[:limit]], "has_more": len(rows) > limit}


# ---------------------------------------------------------------- onboarding


@router.get("/onboarding")
def onboarding() -> dict:
    return {"questions": QUESTIONS, "companions": COMPANIONS}


class Companion(BaseModel):
    species: str
    name: str = Field(min_length=1, max_length=24)


class NewGame(BaseModel):
    about: dict[str, str]
    companion: Companion
    modules: list[dict] = []  # [{template, params}] picked in the "what should I watch for you" step


@router.post("/onboarding")
def new_game(body: NewGame, conn: Conn) -> dict:
    if body.companion.species not in {c["species"] for c in COMPANIONS}:
        raise HTTPException(400, "unknown companion")
    first = not db.get_profile(conn, "onboarded", False)
    with db.transaction(conn):
        db.set_profile(conn, "about", {k: v.strip() for k, v in body.about.items()})
        db.set_profile(conn, "companion", body.companion.model_dump())
        db.set_profile(conn, "onboarded", True)
        if first:
            db.event(conn, "new_game", detail=f"met {body.companion.name}", xp=game.XP["new_game"])
    from tamadesk.api.modules import install_templates  # imports this module

    return {"ok": True, "modules": install_templates(body.modules)}


class AboutField(BaseModel):
    key: str = Field(pattern=r"^[a-z_]{1,24}$")
    value: str = Field(max_length=1000)


@router.post("/about")
def set_about(f: AboutField, conn: Conn) -> dict:
    """Update one answer (e.g. interests) without replaying New Game."""
    about = db.get_profile(conn, "about", {}) | {f.key: f.value.strip()}
    db.set_profile(conn, "about", about)
    return about


class DocIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    data_b64: str = Field(max_length=15_000_000)


@router.get("/docs")
def list_docs(conn: Conn) -> list[dict]:
    return docs.listing(conn)


@router.post("/docs")
def add_doc(d: DocIn, conn: Conn) -> dict:
    try:
        return {"id": docs.add(conn, d.name, d.kind, d.data_b64)}
    except Exception as e:  # an unreadable file is a 422 for the user, not a 500
        raise HTTPException(422, f"couldn't read {d.name}: {e}") from e


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, conn: Conn) -> dict:
    conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
    return {"ok": True}


@router.get("/github")
def github_status(refresh: bool = False) -> dict:
    return github.status(refresh)


# ---------------------------------------------------------------- capture, todos, reminders


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/capture")
def do_capture(body: CaptureIn, conn: Conn) -> dict:
    return actions.capture_text(conn, body.text)


@router.post("/todos/{tid}/{action}")
def todo_action(tid: int, action: Literal["done", "undo", "drop"], conn: Conn) -> dict:
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (tid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such todo")
    xp = 0
    with db.transaction(conn):
        if action == "done" and row["status"] == "open":
            conn.execute("UPDATE todos SET status = 'done', done_at = datetime('now') WHERE id = ?", (tid,))
            xp = game.XP["todo_done"]
            db.event(conn, "todo_done", ref_id=tid, detail=row["title"], xp=xp)
        elif action == "undo" and row["status"] != "open":
            conn.execute("UPDATE todos SET status = 'open', done_at = NULL WHERE id = ?", (tid,))
            # take back the XP so undo can't be farmed
            if row["status"] == "done":
                db.event(conn, "todo_undone", ref_id=tid, detail=row["title"], xp=-game.XP["todo_done"])
        elif action == "drop" and row["status"] == "open":
            conn.execute("UPDATE todos SET status = 'dropped' WHERE id = ?", (tid,))
            db.event(conn, "todo_dropped", ref_id=tid, detail=row["title"])
    return {"ok": True, "xp": xp}


@router.post("/reminders/{rid}/dismiss")
def dismiss(rid: int, conn: Conn) -> dict:
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()
    if not row or row["status"] == "dismissed":
        raise HTTPException(404, "no such reminder")
    xp = game.XP["reminder_done"] if row["status"] == "fired" else 0
    with db.transaction(conn):
        conn.execute("UPDATE reminders SET status = 'dismissed' WHERE id = ?", (rid,))
        db.event(conn, "reminder_done", ref_id=rid, detail=row["text"], xp=xp)
    return {"ok": True, "xp": xp}


@router.get("/log")
def log(conn: Conn, offset: int = 0, limit: int = 50) -> dict:
    rows = conn.execute("SELECT * FROM log_entries ORDER BY id DESC LIMIT ? OFFSET ?",
                        (limit + 1, offset)).fetchall()  # fmt: skip
    return {"items": [dict(r) for r in rows[:limit]], "has_more": len(rows) > limit}


# ---------------------------------------------------------------- writing samples + voice


class SampleIn(BaseModel):
    kind: Literal["email", "essay", "chat", "other"] = "email"
    title: str = ""
    body: str = Field(min_length=40, max_length=20000)


@router.get("/samples")
def samples(conn: Conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM samples ORDER BY id DESC")]


@router.post("/samples")
def add_sample(body: SampleIn, conn: Conn) -> dict:
    rid = conn.execute("INSERT INTO samples (kind, title, body) VALUES (?, ?, ?)",
                       (body.kind, body.title.strip(), body.body.strip())).lastrowid  # fmt: skip
    return {"id": rid}


@router.delete("/samples/{sid}")
def delete_sample(sid: int, conn: Conn) -> dict:
    conn.execute("DELETE FROM samples WHERE id = ?", (sid,))
    return {"ok": True}


@router.get("/voice")
def voice(conn: Conn) -> dict | None:
    return db.get_profile(conn, "voice")


@router.post("/voice/build")
def build_voice(conn: Conn) -> dict:
    try:
        return _brain_call(lambda: writer.build_voice(conn, get_brain(get_settings())))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------- drafts + recap


@router.post("/recap")
def make_recap(conn: Conn) -> dict:
    rows = today_rows(conn)
    if not (rows["log"] or rows["done"] or rows["open"]):
        raise HTTPException(400, "nothing to recap yet: log something or finish a todo first")
    r = _brain_call(lambda: writer.recap(conn, get_brain(get_settings()), rows))
    already = conn.execute(
        "SELECT 1 FROM events WHERE kind = 'recap' AND at >= ?", (day_start_utc(),)
    ).fetchone()
    db.event(conn, "recap", detail=json.dumps(r), xp=0 if already else game.XP["recap"])
    return r


# ---------------------------------------------------------------- settings + brain


@router.get("/brain/check")
def brain_check() -> dict:
    s = get_settings()
    b = get_brain(s)
    ok, detail = b.check()
    return {"ok": ok, "name": b.name, "detail": detail}


class SettingsIn(BaseModel):
    assistant_model: str | None = None
    assistant_effort: Literal["low", "medium", "high"] | None = None
    max_usd_per_ask: float | None = Field(default=None, gt=0, le=10)
    daily_usd: float | None = Field(default=None, gt=0, le=100)
    brain_kind: Literal["claude_code", "ollama"] | None = None
    brain_model: str | None = None
    recap_hour: int | None = Field(default=None, ge=0, le=23)
    todo_goal: int | None = Field(default=None, ge=1, le=20)


@router.put("/settings")
def put_settings(body: SettingsIn) -> dict:
    s = get_settings()
    for key, attr in (("assistant_model", "model"), ("assistant_effort", "effort"),
                      ("max_usd_per_ask", "max_usd_per_ask"), ("daily_usd", "daily_usd")):  # fmt: skip
        if (v := getattr(body, key)) is not None:
            setattr(s.assistant, attr, v)
    if body.brain_kind:
        s.brain.kind = body.brain_kind
    if body.brain_model:
        s.brain.model = body.brain_model.strip()
    if body.recap_hour is not None:
        s.day.recap_hour = body.recap_hour
    if body.todo_goal is not None:
        s.day.todo_goal = body.todo_goal
    save_settings(s)
    return {"ok": True}
