"""FastAPI app: JSON API under /api, the built UI (frontend/dist) at /, and a small scheduler that
rings reminders and writes the evening recap."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tamadesk.api.routes import day_start_utc, router, today_rows
from tamadesk.brain import get_brain
from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import game, writer

log = logging.getLogger("tamadesk")
DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def notify(title: str, body: str) -> None:
    """Best-effort desktop notification (Linux notify-send / macOS osascript)."""
    try:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "tamadesk", title, body], timeout=5, check=False)
        elif shutil.which("osascript"):
            script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        log.warning("desktop notification failed")


def ring_due() -> None:
    conn = db.connect(get_settings().db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= datetime('now')"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE reminders SET status = 'fired', fired_at = datetime('now') WHERE id = ?", (r["id"],)
            )
            companion = (db.get_profile(conn, "companion") or {}).get("name", "tamadesk")
            notify(f"{companion} says", r["text"])
    finally:
        conn.close()


def evening_recap() -> None:
    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        if conn.execute(
            "SELECT 1 FROM events WHERE kind = 'recap' AND at >= ?", (day_start_utc(),)
        ).fetchone():
            return
        rows = today_rows(conn)
        if not (rows["log"] or rows["done"]):
            return
        r = writer.recap(conn, get_brain(s), rows)
        db.event(conn, "recap", detail=json.dumps(r), xp=game.XP["recap"])
        notify("Your day, recapped", r["headline"])
    except Exception:
        log.exception("evening recap failed")
    finally:
        conn.close()


def create_app(scheduler: bool = True) -> FastAPI:
    s = get_settings()
    conn = db.connect(s.db_path)
    db.migrate(conn)
    conn.close()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        sched = None
        if scheduler:
            sched = BackgroundScheduler()  # local time zone, so recap_hour means the user's evening
            sched.add_job(ring_due, "interval", seconds=20, id="ring", max_instances=1, coalesce=True)
            sched.add_job(evening_recap, "cron", hour=s.day.recap_hour, minute=0, id="recap",
                          max_instances=1, coalesce=True)  # fmt: skip
            sched.start()
        yield
        if sched:
            sched.shutdown(wait=False)

    app = FastAPI(title="tamadesk", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
    return app
