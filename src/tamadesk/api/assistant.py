"""Ask API: one request streams the assistant's work (NDJSON events) and saves the conversation."""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from tamadesk.api import jobs
from tamadesk.api.routes import Conn
from tamadesk.assistant import runner
from tamadesk.core import db, usage
from tamadesk.core.config import get_settings
from tamadesk.life import memory

router = APIRouter(prefix="/api")


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    chat_id: int | None = None


@router.post("/ask")
def ask(body: AskIn, conn: Conn) -> StreamingResponse:
    s = get_settings()
    try:
        runner.check_budget(s, conn)
    except runner.BudgetError as e:
        raise HTTPException(429, str(e)) from e
    chat = (
        conn.execute("SELECT * FROM chats WHERE id = ?", (body.chat_id,)).fetchone() if body.chat_id else None
    )
    if chat is None:
        cid = conn.execute("INSERT INTO chats (title) VALUES (?)", (body.text[:80],)).lastrowid
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (cid,)).fetchone()
    conn.execute("INSERT INTO messages (chat_id, role, text) VALUES (?, 'user', ?)", (chat["id"], body.text))
    cmd = runner.command(s, prompt=body.text, system=runner.system_prompt(s, conn),
                         budget=s.assistant.max_usd_per_ask, resume=chat["session_id"])  # fmt: skip

    def events():
        steps, text, c = [], "", db.connect(s.db_path)
        yield json.dumps({"type": "chat", "chat_id": chat["id"]}) + "\n"
        try:
            for ev in runner.stream(s, cmd):
                if ev["type"] == "session" and ev["session_id"]:
                    c.execute("UPDATE chats SET session_id = ? WHERE id = ?", (ev["session_id"], chat["id"]))
                if ev["type"] == "tool":
                    steps.append({"name": ev["name"], "input": ev["input"]})
                if ev["type"] == "done":
                    raw = ev.pop("raw")
                    usage.record(s, "ask", raw)
                    text = (
                        ev["text"]
                        or text
                        or ("I ran out of budget for this one." if "budget" in str(ev["subtype"]) else "")
                    )
                    ev |= {
                        "text": text,
                        "cost_usd": raw.get("total_cost_usd"),
                        "tokens": usage.tokens_of(raw),
                    }
                    c.execute(
                        """INSERT INTO messages (chat_id, role, text, steps, cost_usd, tokens)
                           VALUES (?, 'assistant', ?, ?, ?, ?)""",
                        (chat["id"], text, json.dumps(steps), ev["cost_usd"], ev["tokens"]),
                    )
                    c.execute("UPDATE chats SET updated_at = datetime('now') WHERE id = ?", (chat["id"],))
                if ev["type"] == "text":
                    text += ev["text"]
                yield json.dumps(ev) + "\n"
        finally:
            c.close()

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.get("/chats")
def chats(conn: Conn) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute("SELECT id, title, updated_at FROM chats ORDER BY updated_at DESC LIMIT 30")
    ]


@router.get("/chats/{chat_id}")
def chat(chat_id: int, conn: Conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
    return [dict(r) | {"steps": json.loads(r["steps"] or "[]")} for r in rows]


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: int, conn: Conn) -> dict:
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return {"ok": True}


@router.get("/memory/search")
def memory_search(conn: Conn, q: str, since: str = "", until: str = "") -> list[dict]:
    memory.sync_files(get_settings(), conn)  # pick up hand edits to the day files
    return memory.search(conn, q, since=since, until=until, limit=30)


@router.get("/memory/days")
def memory_days(conn: Conn, offset: int = 0) -> dict:
    memory.sync_files(get_settings(), conn)  # pick up hand edits to the day files
    return {"days": memory.timeline(conn, offset), "pending": memory.pending_days(conn, 60)}


@router.get("/memory/day/{day}")
def memory_day(day: str, conn: Conn) -> dict:
    memory.sync_files(get_settings(), conn)  # pick up hand edits to the day files
    return memory.day_notes(conn, day)


@router.post("/memory/digest")
def memory_digest() -> dict:
    """Summarize finished days that have no memory yet (runs in the background)."""
    threading.Thread(target=jobs.memory_catch_up, args=(10,), daemon=True).start()
    return {"ok": True}


@router.get("/usage")
def usage_today(conn: Conn) -> dict:
    s = get_settings()
    return usage.today(conn) | {"daily_usd": s.assistant.daily_usd, "max_usd_per_ask": s.assistant.max_usd_per_ask,
                                "model": s.assistant.model, "effort": s.assistant.effort}  # fmt: skip
