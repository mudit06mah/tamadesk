"""Run a module (fetch -> dedupe -> rank -> store -> prune) and apply item actions."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from tamadesk.brain import Brain
from tamadesk.core import db
from tamadesk.core.net import NetError, fetch
from tamadesk.life import game
from tamadesk.life.writer import clean
from tamadesk.modules import fit, postings, rank, screen, sources, youtube
from tamadesk.modules.spec import Module

log = logging.getLogger("tamadesk")
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "description": "2-3 plain sentences"},
                   "why_you": {"type": "string", "description": "one line on why it matters to this person, or ''"}},
    "required": ["summary", "why_you"],
}  # fmt: skip


CHECKS_PER_RUN = 25  # postings opened per refresh to confirm they're open; the rest wait for the next one


def check_open(url: str) -> str:
    """open | closed | unknown: is a posting page still taking applications?"""
    try:
        html = fetch(url, timeout=15).decode("utf-8", "replace")
    except NetError as e:
        return "closed" if re.search(r"HTTP Error (?:404|410)", str(e)) else "unknown"
    except Exception:  # noqa: BLE001 - an odd page must not stop the refresh
        return "unknown"
    return postings.page_state(html)


def _gone(conn: sqlite3.Connection, m: Module, source: str, it: sources.Item) -> None:
    """Remember an item we decided against, so it's never fetched, checked or judged again."""
    conn.execute("""INSERT INTO items (module, ext_id, source, title, url, status) VALUES (?,?,?,?,?,'gone')
                    ON CONFLICT(module, ext_id) DO NOTHING""", (m.id, it.ext_id, source, it.title, it.url))  # fmt: skip


def run(conn: sqlite3.Connection, m: Module, *, brain: Brain | None = None, about: dict | None = None,
        check: Callable[[str], str] = check_open) -> dict:  # fmt: skip
    """Fetch every source (and the company job boards this tab learned), keep what's new, fits, is fresh,
    still open and acceptable to the user, then rank and store it. Returns {added, dropped, left_out, errors};
    what was left out is stored as tiny 'gone' rows so it isn't fetched or judged again."""
    errors: list[str] = []
    left: Counter[str] = Counter()
    specs = [x.model_dump() for x in m.sources]
    if m.watch_boards and (watched := [r[0] for r in conn.execute(
            "SELECT board FROM boards WHERE module = ? ORDER BY added_at", (m.id,))]):  # fmt: skip
        specs.append({"type": "company_jobs", "companies": ", ".join(watched), "limit": 1000})
    fresh: list[tuple[str, sources.Item, float | None, list[str]]] = []
    seen: set[str] = set()
    for spec in specs:
        try:
            items = sources.fetch(spec)
        except Exception as e:  # noqa: BLE001 - one dead feed must not stop the others
            errors.append(f"{spec['type']}: {str(e)[:160]}")
            continue
        for it in items:
            if (
                it.ext_id in seen
                or (it.url and it.url in seen)
                or conn.execute(
                    "SELECT 1 FROM items WHERE module = ? AND (ext_id = ? OR (url = ? AND url != ''))",
                    (m.id, it.ext_id, it.url),
                ).fetchone()
            ):
                continue  # seen before: never re-checked or re-counted
            seen |= {it.ext_id, it.url}
            if m.watch_boards and (board := it.data.get("board")):
                conn.execute("INSERT OR IGNORE INTO boards (module, board, found_from) VALUES (?, ?, ?)",
                             (m.id, board, it.url))  # fmt: skip
            ok, f, f_why = fit.keeps(m.fit, it.title, it.body)
            reason = (
                "poor fit"
                if not ok
                else "off topic"
                if not on_topic(m.match, f"{it.title} {it.body}")
                else "too old"
                if postings.too_old(it.published, m.max_age_days)
                else None
            )
            if reason:
                _gone(conn, m, spec["type"], it)
                left[reason] += 1
                continue
            fresh.append((spec["type"], it, f, f_why))
    if (
        m.verify
    ):  # postings found by search: open them and drop the closed ones (boards are live by definition)
        unchecked = [x for x in fresh if x[1].data.get("live") != "open"]
        later = {id(x[1]) for x in unchecked[CHECKS_PER_RUN:]}  # not stored now: checked on a later refresh
        fresh = [x for x in fresh if id(x[1]) not in later]
        todo = unchecked[:CHECKS_PER_RUN]
        with ThreadPoolExecutor(4) as pool:
            for x, state in zip(todo, pool.map(lambda x: check(x[1].url), todo)):
                x[1].data["live"] = state
    verdicts = {}
    if m.screen:
        verdicts = screen.screen(conn, about or {}, [
            {"company": x[1].data.get("company") or postings.host(x[1].url), "text": f"{x[1].title} {x[1].body}"}
            for x in fresh], brain)  # fmt: skip
    added = 0
    for source, it, f, f_why in fresh:
        if it.data.get("live") == "closed":
            _gone(conn, m, source, it)
            left["closed"] += 1
            continue
        v = verdicts.get(screen.key(it.data.get("company") or postings.host(it.url)))
        if v and not v[0]:
            _gone(conn, m, source, it)
            left["against your preferences"] += 1
            continue
        s, why = rank.score(conn, m.id, f"{it.title} {it.body}", m.interests)
        data = it.data | ({"fit": {"score": f, "why": f_why}} if f is not None else {}) | (
            {"screen": v[1]} if v and v[1] else {})  # fmt: skip
        trust = 0.5 if it.data.get("live") == "open" else 0.0  # confirmed open ranks above unknown
        added += conn.execute(
            """INSERT INTO items (module, ext_id, source, title, subtitle, body, url, data, score, why, published_at)
               SELECT ?,?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS
                   (SELECT 1 FROM items WHERE module = ?1 AND url = ?7 AND url != '')
               ON CONFLICT(module, ext_id) DO NOTHING""",
            (m.id, it.ext_id, source, it.title, it.subtitle, it.body, it.url, json.dumps(data),
             s + 3 * (f or 0) + trust, json.dumps(why), it.published),
        ).rowcount  # fmt: skip
    youtube.fill(conn, m.id)  # older video links (e.g. added by Bolt) get their details once
    # keep the database small: beyond the best `keep` unseen items (and old skips), drop the text but
    # keep a tiny 'gone' row so the same item isn't fetched back in; forget those after 90 days
    conn.execute(
        """UPDATE items SET status = 'gone', body = NULL, subtitle = NULL, data = NULL, why = NULL
           WHERE module = ? AND ((status = 'new' AND id NOT IN (SELECT id FROM items WHERE module = ?
                 AND status = 'new' ORDER BY score DESC, id DESC LIMIT ?))
              OR (status = 'new' AND created_at < datetime('now', ?))
              OR (status = 'skipped' AND decided_at < datetime('now', '-30 days')))""",
        (m.id, m.id, m.keep, f"-{m.expire_days} days"),
    )
    conn.execute("DELETE FROM items WHERE module = ? AND status = 'gone' AND created_at < datetime('now', '-90 days')",
                 (m.id,))  # fmt: skip
    conn.execute(
        """INSERT INTO module_runs (module, last_run, last_error, added, dropped, left_out)
           VALUES (?, datetime('now'), ?, ?, ?, ?)
           ON CONFLICT(module) DO UPDATE SET last_run = excluded.last_run, last_error = excluded.last_error,
                                             added = excluded.added, dropped = excluded.dropped,
                                             left_out = excluded.left_out""",
        (
            m.id,
            "; ".join(errors) or None,
            added,
            sum(left.values()),
            json.dumps(dict(left)) if left else None,
        ),
    )
    return {"added": added, "dropped": sum(left.values()), "left_out": dict(left), "errors": errors}


def recheck_kept(
    conn: sqlite3.Connection, *, check: Callable[[str], str] = check_open, limit: int = 30
) -> int:
    """Kept postings you haven't acted on yet: are they still open? A closed one is marked (its card
    says so, and Up next stops asking you to apply). Each is checked at most every 3 days. Returns how
    many closed."""
    rows = conn.execute(
        """SELECT id, data FROM items WHERE status = 'saved' AND stage IS NULL AND data LIKE '%"apply_url"%'
           AND data NOT LIKE '%"closed_at"%' AND coalesce(json_extract(data, '$.checked_at'), '') <
               datetime('now', '-3 days') ORDER BY decided_at LIMIT ?""",
        (limit,),
    ).fetchall()
    closed = 0
    for r in rows:
        data = json.loads(r["data"] or "{}")
        state = check(data.get("apply_url") or "")
        stamp = conn.execute("SELECT datetime('now')").fetchone()[0]
        data["checked_at"] = stamp
        if state == "closed":
            data["closed_at"] = stamp
            closed += 1
        conn.execute("UPDATE items SET data = ? WHERE id = ?", (json.dumps(data), r["id"]))
    return closed


def on_topic(match: list[str], text: str) -> bool:
    """Does the text mention at least one of the tab's match words? (No match words: always.) Whole
    words, any case: 'Musk' isn't found in 'muskrat', and 'Elon Musk' needs both words in a row."""
    return not match or any(re.search(rf"(?<!\w){re.escape(w.strip())}(?!\w)", text, re.IGNORECASE)
                            for w in match if w.strip())  # fmt: skip


def rescore(conn: sqlite3.Connection, m: Module) -> None:
    """Re-rank unseen items after the taste model learned something or the tab changed. Unseen items
    that no longer fit are dropped (kept ones never are: the user chose them)."""
    rows = conn.execute(
        "SELECT id, title, body, url, data FROM items WHERE module = ? AND status = 'new'", (m.id,)
    ).fetchall()
    for r in rows:
        ok, f, f_why = fit.keeps(m.fit, r["title"], r["body"] or "")
        ok = ok and on_topic(
            m.match, f"{r['title']} {r['body'] or ''}"
        )  # a tightened topic clears what's off it
        if ok and m.verify and r["url"] and postings.kind(r["url"]) == "board":
            ok = False  # a tab that wants original postings: unseen aggregator items go
        if not ok:
            conn.execute(
                "UPDATE items SET status = 'gone', body = NULL, data = NULL WHERE id = ?", (r["id"],)
            )
            continue
        data = json.loads(r["data"] or "{}")
        data.pop("fit", None)
        data |= {"fit": {"score": f, "why": f_why}} if f is not None else {}
        sc, why = rank.score(conn, m.id, f"{r['title']} {r['body']}", m.interests)
        conn.execute("UPDATE items SET score = ?, why = ?, data = ? WHERE id = ?",
                     (sc + 3 * (f or 0), json.dumps(why), json.dumps(data), r["id"]))  # fmt: skip


STATUS = {"save": "saved", "skip": "skipped", "done": "done"}


def act(conn: sqlite3.Connection, item_id: int, action: str, *, reason: str = "") -> dict:
    """save / skip / done / undo. Decisions teach the ranker and give a little XP."""
    it = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if it is None:
        raise KeyError(item_id)
    text = f"{it['title']} {it['body']}"
    with db.transaction(conn):
        if action == "undo":
            if it["status"] in ("saved", "skipped"):
                rank.learn(conn, it["module"], text, liked=it["status"] == "skipped")  # cancel it out
            conn.execute(
                "UPDATE items SET status = 'new', decided_at = NULL, reason = NULL WHERE id = ?", (item_id,)
            )
            return {"status": "new", "xp": 0}
        status = STATUS[action]
        if it["status"] == "new" and action in ("save", "skip"):
            rank.learn(conn, it["module"], text, liked=action == "save")
        conn.execute("UPDATE items SET status = ?, decided_at = datetime('now'), reason = ? WHERE id = ?",
                     (status, reason or None, item_id))  # fmt: skip
        xp = game.XP["triaged"] if it["status"] == "new" else 0
        db.event(conn, f"item_{status}", ref_id=item_id, detail=f"{it['module']}: {it['title'][:80]}", xp=xp)
    return {"status": status, "xp": xp}


def summarize(conn: sqlite3.Connection, brain: Brain, item_id: int, about: str) -> dict:
    """On-demand, cached: read the page (Jina, free) and have the light model summarize it."""
    it = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    data = json.loads(it["data"] or "{}")
    if "summary" in data:
        return data["summary"]
    text = it["body"] or ""
    if it["url"] and (spoken := sources.transcript(it["url"])):  # a video: what's actually said in it
        text = f"Description: {text}\n\nTranscript: {spoken}"
    elif it["url"] and len(text) < 400:
        try:
            text = sources.read_page(it["url"])
        except Exception:  # noqa: BLE001 - fall back to what we have
            log.info("page read failed for %s", it["url"])
    out = brain.ask(
        f"Summarize this for a busy person.\nAbout them: {about}\n\nTitle: {it['title']}\n\n{text[:9000]}",
        SUMMARY_SCHEMA,
        light=True,
        kind="summary",
    )
    data["summary"] = out = {k: clean(v) for k, v in out.items()}
    conn.execute("UPDATE items SET data = ? WHERE id = ?", (json.dumps(data), item_id))
    return out
