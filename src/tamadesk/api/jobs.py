"""The one background scheduler: reminder rings, the evening recap, the inbox and calendar, and each
module's fetches.

Two worker threads at most, so fetching never competes with the rest of the machine.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from tamadesk.api.routes import day_start_utc, today_rows
from tamadesk.brain import get_brain
from tamadesk.core import clock, db
from tamadesk.core.config import Settings, get_settings
from tamadesk.life import game, writer
from tamadesk.modules import engine, spec

log = logging.getLogger("tamadesk")
_sched: BackgroundScheduler | None = None
ONCE = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600}


def notify(title: str, body: str, kind: str = "news") -> None:
    """Ring now or hold for later, by the user's quiet hours and focus (life/notify.py)."""
    from tamadesk.life import notify as notifying

    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        notifying.ping(s, conn, kind, title, body)
    finally:
        conn.close()


def ring_due() -> None:
    """Fire due reminders. A repeating one schedules its next ring at the same moment."""
    from tamadesk.life import repeat as repeating

    conn = db.connect(get_settings().db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= datetime('now')"
        ).fetchall()
        companion = (db.get_profile(conn, "companion") or {}).get("name", "tamadesk")
        for r in rows:
            conn.execute(
                "UPDATE reminders SET status = 'fired', fired_at = datetime('now') WHERE id = ?", (r["id"],)
            )
            if r["repeat"]:
                due = clock.local_naive(r["due_at"])
                nxt = repeating.next_after(r["repeat"], max(due, datetime.now().astimezone().replace(tzinfo=None)),
                                           (due.hour, due.minute))  # fmt: skip
                conn.execute("INSERT INTO reminders (text, due_at, repeat) VALUES (?, ?, ?)",
                             (r["text"], clock.sql_ts(clock.to_utc(nxt)), r["repeat"]))  # fmt: skip
            notify(f"{companion} says", r["text"], "meeting" if r["cal_key"] else "reminder")
    finally:
        conn.close()


def focus_and_pings() -> None:
    """Every minute: close a focus session whose time is up (it rings: you earned it), then deliver
    the notifications that waited, if now is a good moment."""
    from tamadesk.life import focus
    from tamadesk.life import notify as notifying

    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        if done := focus.finish_due(conn):
            notifying.ping(
                s, conn, "focus", "Focus done!", f"{done['minutes']} minutes, +{done['xp']} XP. Stretch?"
            )
        notifying.flush(s, conn)
    except Exception:
        log.exception("focus/pings job failed")
    finally:
        conn.close()


def evening_recap() -> None:
    """At the recap hour: write the day's recap once (light brain), if anything happened today."""
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
        notify("Your day, recapped", r["headline"], "recap")
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
                       f"{m['from_name'] or m['from_addr']}: {m['subject']}", "inbox")  # fmt: skip
    except Exception:
        log.exception("inbox check failed")
    finally:
        conn.close()


def profile_card() -> None:
    """Right after a resume is added (or on "rebuild"): write the profile card with the light brain."""
    from tamadesk.brain import BrainError
    from tamadesk.life import profile

    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        profile.build(s, conn, get_brain(s))
        db.set_profile(
            conn, "profile_card", {"state": "ready", "at": datetime.now().astimezone().isoformat()}
        )
    except (BrainError, OSError, KeyError, TypeError) as e:
        log.warning("profile card failed: %s", e)
        db.set_profile(conn, "profile_card", {"state": "error", "error": str(e)[:200]})
    finally:
        conn.close()


def calendar_sync() -> None:
    """Every 15 minutes: the private iCal feed, if the user set one."""
    from tamadesk.life import calendar

    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        calendar.sync_feed(s, conn)
        calendar.sync_deadlines(s, conn)
    except Exception:
        log.exception("calendar sync failed")
    finally:
        conn.close()


def calendar_alerts() -> None:
    """Every minute: meetings starting soon become reminders, which ring_due then rings."""
    from tamadesk.life import calendar

    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        calendar.alerts(s, conn)
    except Exception:
        log.exception("calendar alerts failed")
    finally:
        conn.close()


def deadline_nudges() -> None:
    """Every minute: a todo whose deadline just got closer (a day, 3 hours, an hour, due) pings once."""
    from tamadesk.life import pressure

    conn = db.connect(get_settings().db_path)
    try:
        style = pressure.tone(db.get_profile(conn, "about", {}).get("nudge"))
        companion = (db.get_profile(conn, "companion") or {}).get("name", "tamadesk")
        for stage, text in pressure.due_nudges(conn, style):
            notify(f"{companion} says", text, "deadline_now" if stage >= 3 else "deadline")
    except Exception:
        log.exception("deadline nudges failed")
    finally:
        conn.close()


def recheck_postings() -> None:
    """Daily: are the jobs you kept (and haven't applied to) still open?"""
    conn = db.connect(get_settings().db_path)
    try:
        if n := engine.recheck_kept(conn):
            log.info("%d kept posting(s) closed", n)
    except Exception:
        log.exception("posting recheck failed")
    finally:
        conn.close()


def github_refresh() -> None:
    """Every 10 minutes, if `gh` is set up: what GitHub needs from you, so Today reads it instantly."""
    from tamadesk.life import github

    if shutil.which("gh"):
        try:
            github.status(refresh=True)
        except Exception:
            log.exception("github refresh failed")


def run_module(module_id: str) -> None:
    """Refresh one tab: fetch, filter and rank its sources (engine.run), and ping if it asked to."""
    s = get_settings()
    m = spec.get(s, module_id)
    if m is None:
        return
    conn = db.connect(s.db_path)
    try:
        # screening asks the user's own brain (light, capped) about companies it hasn't judged yet
        about = db.get_profile(conn, "about", {}) if m.screen else None
        r = engine.run(conn, m, brain=get_brain(s) if m.screen else None, about=about)
        log.info("module %s: +%d items %s", module_id, r["added"], r["errors"] or "")
        if m.notify and r["added"]:
            notify(m.name, f"{r['added']} new", "tab")
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


def run_once(fn, job_id: str) -> None:
    """Run a job soon on the scheduler (e.g. a calendar sync right after the feed is set)."""
    if _sched is not None:
        _sched.add_job(
            fn, id=job_id, replace_existing=True, next_run_time=datetime.now().astimezone(), **ONCE
        )


def run_now(module_id: str) -> None:
    """Refresh a tab right away, on the scheduler's threads."""
    if _sched is not None:
        _sched.add_job(run_module, args=[module_id], id=f"now:{module_id}", replace_existing=True,
                       next_run_time=datetime.now().astimezone(), **ONCE)  # fmt: skip


def schedule_recap(s: Settings) -> None:
    """Write the recap at the user's bedtime (moved whenever they change it)."""
    if _sched is not None:
        h, m = map(int, s.day.bed_at.split(":"))
        _sched.add_job(evening_recap, "cron", hour=h, minute=m, id="recap", replace_existing=True, **ONCE)


def start(s: Settings) -> None:
    """Start the background scheduler: two worker threads for fetching, a separate one for rings."""
    global _sched
    # local tz (bedtime is yours); fetches share 2 threads, reminders get their own so they're never late
    _sched = BackgroundScheduler(executors={"default": ThreadPoolExecutor(2), "ring": ThreadPoolExecutor(1)})
    _sched.add_job(ring_due, "interval", seconds=20, id="ring", executor="ring", **ONCE)
    schedule_recap(s)
    _sched.add_job(memory_catch_up, "cron", hour=3, minute=30, id="memory", **ONCE)
    _sched.add_job(inbox_check, "interval", minutes=10, id="inbox", **ONCE)
    _sched.add_job(calendar_sync, "interval", minutes=15, id="calendar", next_run_time=datetime.now().astimezone(),
                   **ONCE)  # fmt: skip
    _sched.add_job(calendar_alerts, "interval", minutes=1, id="cal-alerts", executor="ring", **ONCE)
    _sched.add_job(deadline_nudges, "interval", minutes=1, id="deadlines", executor="ring", **ONCE)
    _sched.add_job(focus_and_pings, "interval", minutes=1, id="focus-pings", executor="ring", **ONCE)
    _sched.add_job(recheck_postings, "cron", hour=10, minute=30, id="postings", **ONCE)
    _sched.add_job(github_refresh, "interval", minutes=10, id="github", next_run_time=datetime.now().astimezone()
                   + timedelta(seconds=30), **ONCE)  # fmt: skip
    _sched.add_job(memory_catch_up, id="memory-boot", next_run_time=datetime.now().astimezone() + timedelta(minutes=2),
                   **ONCE)  # fmt: skip
    _sched.start()
    sync_modules(s)


def stop() -> None:
    """Stop the scheduler (on shutdown)."""
    global _sched
    if _sched:
        _sched.shutdown(wait=False)
    _sched = None
