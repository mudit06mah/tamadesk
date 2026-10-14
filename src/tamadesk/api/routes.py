"""JSON API for the desk: state, quick capture, todos, reminders, log, samples, drafts, recap."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from tamadesk.brain import BrainError, get_brain
from tamadesk.core import clock, db
from tamadesk.core.config import HHMM, get_settings, save_settings
from tamadesk.life import (
    actions,
    calendar,
    docs,
    focus,
    game,
    github,
    mail,
    pipeline,
    profile,
    suggest,
    today,
    upnext,
    writer,
)
from tamadesk.life.onboarding import COMPANIONS, QUESTIONS

router = APIRouter(prefix="/api")


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


day_start_utc = clock.day_start_utc  # kept for importers; the rule lives in core/clock.py


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
        code = 429 if e.kind == "budget" else 503 if e.kind in {"unavailable", "rate_limit"} else 502
        raise HTTPException(code, str(e)) from e


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
        "needs_you": len(today.needs_you(conn)),
        "brain": {"kind": s.brain.kind, "model": s.brain.model},
        "day": {"wake": s.day.wake, "bed": s.day.bed_at, "today": clock.today().isoformat(),
                "todo_goal": s.day.todo_goal, "quiet_start": s.day.quiet_start, "quiet_end": s.day.quiet_end},
        "focus": focus.running(conn),
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


class DayIn(BaseModel):
    wake: str = Field(pattern=HHMM)
    bed: str = Field(pattern=HHMM)


class NewGame(BaseModel):
    about: dict[str, str]
    companion: Companion
    modules: list[dict] = []  # [{template, params}] picked in the "what should I watch for you" step
    day: DayIn | None = None  # when they usually wake and go to bed: the day's span and the recap time


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
    if body.day:
        _set_day(body.day.wake, body.day.bed)
    from tamadesk.api.modules import install_templates  # imports this module

    return {"ok": True, "modules": install_templates(body.modules)}


class SpeciesIn(BaseModel):
    species: str


@router.post("/companion")
def switch_companion(b: SpeciesIn, conn: Conn) -> dict:
    """Swap who sits on your desk. A name that was just the old species' name follows the new one."""
    labels = {c["species"]: c["label"] for c in COMPANIONS}
    if b.species not in labels:
        raise HTTPException(400, "unknown companion")
    cur = db.get_profile(conn, "companion") or {"species": b.species, "name": labels[b.species]}
    name = labels[b.species] if cur["name"] in labels.values() else cur["name"]
    db.set_profile(conn, "companion", {"species": b.species, "name": name})
    return {"species": b.species, "name": name}


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
    return [d for d in docs.listing(conn) if d["kind"] != "note"]  # notes have their own page


@router.post("/docs")
def add_doc(d: DocIn, conn: Conn) -> dict:
    try:
        doc_id = docs.add(conn, d.name, d.kind, d.data_b64)
    except Exception as e:  # an unreadable file is a 422 for the user, not a 500
        raise HTTPException(422, f"couldn't read {d.name}: {e}") from e
    if d.kind == "resume":
        _build_card(conn)
    return {"id": doc_id}


def _build_card(conn: sqlite3.Connection) -> None:
    from tamadesk.api import jobs  # imports this module

    db.set_profile(conn, "profile_card", {"state": "building"})
    jobs.run_once(jobs.profile_card, "profile-card")


@router.get("/profile")
def get_card(conn: Conn) -> dict:
    """The profile card (memory/profile.md) and whether one is being written."""
    s = get_settings()
    return {"text": profile.read(s), "has_resume": profile.resume(conn) is not None,
            **db.get_profile(conn, "profile_card", {"state": "none"})}  # fmt: skip


class CardIn(BaseModel):
    text: str = Field(max_length=20_000)


@router.put("/profile")
def save_card(b: CardIn) -> dict:
    profile.save(get_settings(), b.text)
    return {"ok": True}


@router.post("/profile/rebuild")
def rebuild_card(conn: Conn) -> dict:
    if profile.resume(conn) is None:
        raise HTTPException(400, "add a resume first")
    _build_card(conn)
    return {"state": "building"}


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, conn: Conn) -> dict:
    conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
    return {"ok": True}


@router.get("/next")
def next_up(conn: Conn) -> list[dict]:
    return upnext.up_next(conn)


class StageIn(BaseModel):
    stage: str


@router.post("/items/{item_id}/stage")
def item_stage(item_id: int, b: StageIn, conn: Conn) -> dict:
    with db.transaction(conn):
        changed = pipeline.set_stage(conn, item_id, b.stage, why="you said so", manual=True)
    return {"changed": changed}


@router.get("/notes")
def notes(conn: Conn) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, text, created_at FROM docs WHERE kind = 'note' ORDER BY id DESC"
        )
    ]


class NoteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=60_000)


@router.put("/notes/{note_id}")
def edit_note(note_id: int, n: NoteIn, conn: Conn) -> dict:
    conn.execute(
        "UPDATE docs SET name = ?, text = ? WHERE id = ? AND kind = 'note'", (n.name, n.text, note_id)
    )
    return {"ok": True}


@router.get("/today")
def today_view(conn: Conn, day: str = "") -> dict:
    """The day as one list: what needs you, the timeline, and undated todos (`day` = YYYY-MM-DD)."""
    try:
        d = date.fromisoformat(day) if day else None
    except ValueError as e:
        raise HTTPException(400, "day must be YYYY-MM-DD") from e
    return today.day(conn, d, recap_at=get_settings().day.bed_at)


class AskTipIn(BaseModel):
    target: Literal["draft", "inbox"]
    id: int


@router.post("/suggestions/ask")
def suggestion_ask(b: AskTipIn, conn: Conn) -> list[dict]:
    """The only Claude call here, and only on a click: up to two more things only the user can do."""
    if suggest.asked(conn, b.target, b.id):
        return suggest.open_for(conn, b.target, b.id)
    return _brain_call(lambda: suggest.ask_claude(conn, get_brain(get_settings()), b.target, b.id))


@router.post("/suggestions/{sid}/{action}")
def suggestion_action(sid: int, action: Literal["done", "undo", "dismiss", "remind"], conn: Conn) -> dict:
    """Tick, untick or dismiss an "only you" suggestion, or set a reminder before its deadline."""
    try:
        if action == "remind":
            return {"reminder_at": suggest.remind(conn, sid)}
        return suggest.act(conn, sid, action)
    except KeyError as e:
        raise HTTPException(404, "no such suggestion") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class PromisesIn(BaseModel):
    cal_key: str = Field(max_length=400)
    lines: list[str] = Field(default=[], max_length=20)  # empty: "nothing this time"


@router.post("/meetings/promises")
def meeting_promises(b: PromisesIn, conn: Conn) -> dict:
    """What you promised in a meeting that just ended: each line becomes a todo linked to it."""
    lines = [x.strip() for x in b.lines if x.strip()]
    with db.transaction(conn):
        ids = [actions.add_todo(conn, x[:200], cal_key=b.cal_key) for x in lines]
        conn.execute("INSERT OR REPLACE INTO meeting_notes (cal_key, status) VALUES (?, ?)",
                     (b.cal_key, "added" if ids else "nothing"))  # fmt: skip
    return {"todos": ids}


class FocusIn(BaseModel):
    minutes: int = Field(default=25, ge=5, le=180)
    tag: str = Field(default="", max_length=30)


@router.get("/focus")
def focus_now(conn: Conn) -> dict:
    return {"running": focus.running(conn), "done_today": conn.execute(
        "SELECT count(*) FROM focus WHERE status = 'done' AND started_at >= ?", (day_start_utc(),)).fetchone()[0]}  # fmt: skip


@router.post("/focus")
def focus_start(b: FocusIn, conn: Conn) -> dict:

    return focus.start(conn, b.minutes, re.sub(r"[^\w-]", "", b.tag.lstrip("#")).lower())


@router.post("/focus/{action}")
def focus_end(action: Literal["stop", "finish"], conn: Conn) -> dict:
    """stop: early, no XP. finish: only once the time is really up (the job does it too, if the tab is closed)."""

    if action == "stop":
        return {"stopped": focus.stop(conn) is not None, "xp": 0}
    done = focus.finish_due(conn)
    return {"finished": done is not None, "xp": done["xp"] if done else 0}


@router.get("/review/{kind}")
def review_view(kind: Literal["standup", "week", "brag"], conn: Conn, since: str = "") -> dict:
    """Free looking-back: a standup note, the week card, or a brag doc since a day (YYYY-MM-DD)."""
    from datetime import timedelta

    from tamadesk.life import review

    if kind == "standup":
        return review.standup(conn)
    if kind == "week":
        return review.week(conn)
    try:
        start = date.fromisoformat(since) if since else today.local_today() - timedelta(days=90)
    except ValueError as e:
        raise HTTPException(400, "since must be YYYY-MM-DD") from e
    return review.brag(conn, start)


class NoteNew(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=60_000)


@router.post("/notes")
def new_note(n: NoteNew, conn: Conn) -> dict:
    return {"id": docs.save_note(conn, n.name, n.text)}


@router.get("/tips")
def tips_now(conn: Conn) -> list[str]:
    """Shortcuts this person hasn't tried yet, for the Ask box's example chips."""
    from tamadesk.life import tips

    return tips.untried(conn)


class SeenIn(BaseModel):
    kind: Literal["gh"]
    key: str = Field(max_length=100)


@router.post("/seen")
def mark_seen(b: SeenIn, conn: Conn) -> dict:
    """Dismiss something locally (a GitHub notification): nothing is changed on GitHub."""
    conn.execute("INSERT OR IGNORE INTO seen (kind, key) VALUES (?, ?)", (b.kind, b.key))
    return {"ok": True}


@router.get("/calendar")
def calendar_status(conn: Conn) -> dict:
    return calendar.status(get_settings(), conn)


class DeadlineFeed(BaseModel):
    url: str = Field(max_length=2000)
    tag: str = Field(min_length=1, max_length=30)


class CalendarIn(BaseModel):
    add_deadline_feed: DeadlineFeed | None = None  # a feed whose events become todos with deadlines
    remove_deadline_feed: str | None = None  # by tag
    feed: str | None = Field(default=None, max_length=2000)  # "" removes it; None keeps it
    from_mail: bool | None = None
    remind_min: int | None = Field(default=None, ge=0, le=120)


@router.put("/calendar")
def calendar_setup(b: CalendarIn, conn: Conn) -> dict:
    s = get_settings()
    if b.feed is not None:
        feed = b.feed.strip()
        if feed and not re.match(r"^(https|webcal)://", feed):
            raise HTTPException(400, "paste the private address in iCal format (https:// or webcal://)")
        mail.set_secret(s, calendar.FEED_SECRET, feed)
        if not feed:
            db.set_profile(conn, "calendar_feed_error", None)
    feeds = calendar.deadline_feeds(s)
    if (f := b.add_deadline_feed) is not None:
        if not re.match(r"^(https|webcal)://", f.url.strip()):
            raise HTTPException(400, "paste the calendar's iCal address (https:// or webcal://)")
        tag = re.sub(r"[^\w-]", "", f.tag.lstrip("#")).lower() or "deadline"
        feeds = [x for x in feeds if x.get("tag") != tag] + [{"url": f.url.strip(), "tag": tag}]
        mail.set_secret(s, calendar.DEADLINE_SECRET, feeds)
    if b.remove_deadline_feed:
        mail.set_secret(
            s, calendar.DEADLINE_SECRET, [x for x in feeds if x.get("tag") != b.remove_deadline_feed]
        )
    if b.from_mail is not None:
        s.calendar.from_mail = b.from_mail
    if b.remind_min is not None:
        s.calendar.remind_min = b.remind_min
    save_settings(s)
    if b.feed or b.add_deadline_feed:
        from tamadesk.api import jobs  # imports this module

        jobs.run_once(jobs.calendar_sync, "calendar-now")
    return calendar.status(s, conn)


@router.post("/calendar/sync")
def calendar_sync(conn: Conn) -> dict:
    s = get_settings()
    n = calendar.sync_feed(s, conn)
    return calendar.status(s, conn) | {"changed": n}


@router.get("/github")
def github_status(refresh: bool = False) -> dict:
    return github.status(refresh)


# ---------------------------------------------------------------- capture, todos, reminders


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/capture")
def do_capture(body: CaptureIn, conn: Conn) -> dict:
    return actions.capture_text(conn, body.text)


class DueIn(BaseModel):
    when: str = Field(max_length=100)  # 'fri 5pm', 'in 2 days'; '' clears the deadline


@router.put("/todos/{tid}/due")
def todo_due(tid: int, b: DueIn, conn: Conn) -> dict:
    try:
        return {"due_at": actions.set_due(conn, tid, b.when)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/todos/{tid}/{action}")
def todo_action(tid: int, action: Literal["done", "undo", "drop"], conn: Conn, stop: bool = False) -> dict:
    """done / undo / drop. For a repeating todo, drop skips this time; drop?stop=true ends the series."""
    if not conn.execute("SELECT 1 FROM todos WHERE id = ?", (tid,)).fetchone():
        raise HTTPException(404, "no such todo")
    if action == "done":
        return {"ok": True, "xp": 0} | actions.complete_todo(conn, tid)
    if action == "undo":
        return {"ok": True, "xp": actions.undo_todo(conn, tid)}
    actions.drop_todo(conn, tid, stop=stop)
    return {"ok": True, "xp": 0}


@router.post("/reminders/{rid}/cancel")
def cancel(rid: int, conn: Conn) -> dict:
    return {"ok": actions.cancel_reminder(conn, rid)}


class RepeatIn(BaseModel):
    repeat: str | None = None  # None stops repeating


@router.put("/todos/{tid}/repeat")
def todo_repeat(tid: int, b: RepeatIn, conn: Conn) -> dict:
    actions.set_repeat(conn, tid, b.repeat)
    return {"ok": True}


@router.post("/reminders/{rid}/dismiss")
def dismiss(rid: int, conn: Conn) -> dict:
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()
    if not row or row["status"] == "dismissed":
        raise HTTPException(404, "no such reminder")
    # a meeting alert is the calendar talking, not something the user finished
    xp = game.XP["reminder_done"] if row["status"] == "fired" and not row["cal_key"] else 0
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
def voice(conn: Conn) -> dict:
    """The studied voice plus the user's own rules (from redraft feedback or added by hand)."""
    return {"voice": db.get_profile(conn, "voice"), "rules": db.get_profile(conn, "writing_feedback", [])}


class VoiceEdit(BaseModel):
    summary: str | None = None
    do: list[str] | None = None
    dont: list[str] | None = None
    phrases: list[str] | None = None
    rules: list[str] | None = None


@router.put("/voice")
def edit_voice(v: VoiceEdit, conn: Conn) -> dict:
    """Direct the voice: change the overview, drop points you disagree with, add your own rules."""
    cur = db.get_profile(conn, "voice") or {"summary": "", "traits": [], "do": [], "dont": [], "phrases": []}
    patch = {k: val for k, val in v.model_dump(exclude={"rules"}).items() if val is not None}
    if patch:
        db.set_profile(conn, "voice", cur | patch)
    if v.rules is not None:
        db.set_profile(conn, "writing_feedback", [r.strip() for r in v.rules if r.strip()][-25:])
    return voice(conn)


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
    wake: str | None = Field(default=None, pattern=HHMM)
    bed: str | None = Field(default=None, pattern=HHMM)
    quiet_start: int | None = Field(default=None, ge=-1, le=23)  # -1 turns quiet hours off
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    todo_goal: int | None = Field(default=None, ge=1, le=20)


def _set_day(wake: str, bed: str) -> None:
    """Their day runs wake to bed: the recap moves to bedtime, and quiet hours (if they haven't set
    their own) cover the night."""
    s = get_settings()
    s.day.wake, s.day.bed = wake, bed
    if s.day.quiet_start is None:
        s.day.quiet_start, s.day.quiet_end = int(bed[:2]), int(wake[:2])
    save_settings(s)
    from tamadesk.api import jobs  # imports this module

    jobs.schedule_recap(s)


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
    if body.wake or body.bed:
        s.day.wake, s.day.bed = body.wake or s.day.wake, body.bed or s.day.bed_at
    if body.todo_goal is not None:
        s.day.todo_goal = body.todo_goal
    if body.quiet_start is not None:
        s.day.quiet_start = None if body.quiet_start < 0 else body.quiet_start
        s.day.quiet_end = None if body.quiet_start < 0 else body.quiet_end
    save_settings(s)
    if body.bed:
        from tamadesk.api import jobs  # imports this module

        jobs.schedule_recap(s)  # the recap moves with bedtime, no restart needed
    return {"ok": True}
