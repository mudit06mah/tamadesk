"""The one background scheduler: reminder rings, the evening recap, and each module's fetches.

Two worker threads at most, so fetching never competes with the rest of the machine.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from tamadesk.api.routes import day_start_utc, today_rows
from tamadesk.brain import get_brain
from tamadesk.core import db
from tamadesk.core.config import Settings, get_settings
from tamadesk.life import game, writer
from tamadesk.modules import engine, spec

log = logging.getLogger("tamadesk")
_sched: BackgroundScheduler | None = None
ONCE = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600}


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


def memory_catch_up(limit: int = 5) -> int:
    """Digest finished days that have no memory yet (light model, within the daily budget)."""
    from tamadesk.assistant.runner import BudgetError, check_budget
    from tamadesk.life import memory

    s = get_settings()
    conn = db.connect(s.db_path)
    done = 0
    try:
        memory.sync_files(s, conn)
        for day in memory.pending_days(conn, limit):
            try:
                check_budget(s, conn)
                memory.digest(s, conn, get_brain(s), day)
                done += 1
            except BudgetError:
                break
            except Exception:
                log.exception("memory digest failed for %s", day)
    finally:
        conn.close()
    return done


def inbox_check() -> None:
    """Every few minutes: new replies / portal mail for things the user started. Pings for the ones that matter."""
    from tamadesk.life import inbox, mail

    s = get_settings()
    if not mail.ready(s):
        return
    conn = db.connect(s.db_path)
    try:
        for m in inbox.check(s, conn):
            if m["kind"] in ("reply", "interview", "bounce"):
                notify({"reply": "New reply", "interview": "Interview invite", "bounce": "Email bounced"}[m["kind"]],
                       f"{m['from_name'] or m['from_addr']}: {m['subject']}")  # fmt: skip
    except Exception:
        log.exception("inbox check failed")
    finally:
        conn.close()


def run_module(module_id: str) -> None:
    s = get_settings()
    m = spec.get(s, module_id)
    if m is None:
        return
    conn = db.connect(s.db_path)
    try:
        r = engine.run(conn, m)
        log.info("module %s: +%d items %s", module_id, r["added"], r["errors"] or "")
        if m.notify and r["added"]:
            notify(m.name, f"{r['added']} new")
    finally:
        conn.close()


def sync_modules(s: Settings) -> None:
    """Make the scheduler match the modules on disk (after create, edit or delete)."""
    if _sched is None:
        return
    mods = {m.id: m for m in spec.load_all(s)}
    for job in _sched.get_jobs():
        if job.id.startswith("mod:") and job.id[4:] not in mods:
            job.remove()
    for m in mods.values():
        trig, kw = spec.trigger(m.every)
        _sched.add_job(run_module, trig, args=[m.id], id=f"mod:{m.id}", replace_existing=True, **kw, **ONCE)


def run_now(module_id: str) -> None:
    if _sched is not None:
        _sched.add_job(run_module, args=[module_id], id=f"now:{module_id}", replace_existing=True,
                       next_run_time=datetime.now().astimezone(), **ONCE)  # fmt: skip


def start(s: Settings) -> None:
    global _sched
    # local tz (recap_hour is yours); fetches share 2 threads, reminders get their own so they're never late
    _sched = BackgroundScheduler(executors={"default": ThreadPoolExecutor(2), "ring": ThreadPoolExecutor(1)})
    _sched.add_job(ring_due, "interval", seconds=20, id="ring", executor="ring", **ONCE)
    _sched.add_job(evening_recap, "cron", hour=s.day.recap_hour, minute=0, id="recap", **ONCE)
    _sched.add_job(memory_catch_up, "cron", hour=3, minute=30, id="memory", **ONCE)
    _sched.add_job(inbox_check, "interval", minutes=10, id="inbox", **ONCE)
    _sched.add_job(memory_catch_up, id="memory-boot", next_run_time=datetime.now().astimezone() + timedelta(minutes=2),
                   **ONCE)  # fmt: skip
    _sched.start()
    sync_modules(s)


def stop() -> None:
    global _sched
    if _sched:
        _sched.shutdown(wait=False)
    _sched = None
