"""Run a module (fetch -> dedupe -> rank -> store -> prune) and apply item actions."""

from __future__ import annotations

import json
import logging
import sqlite3

from tamadesk.brain import Brain
from tamadesk.core import db
from tamadesk.life import game
from tamadesk.life.writer import clean
from tamadesk.modules import rank, sources
from tamadesk.modules.spec import Module

log = logging.getLogger("tamadesk")
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string", "description": "2-3 plain sentences"},
                   "why_you": {"type": "string", "description": "one line on why it matters to this person, or ''"}},
    "required": ["summary", "why_you"],
}  # fmt: skip


def run(conn: sqlite3.Connection, m: Module) -> dict:
    """Fetch every source; new items are ranked and stored. Returns {added, errors}."""
    added, errors = 0, []
    for spec in m.sources:
        try:
            items = sources.fetch(spec.model_dump())
        except Exception as e:  # noqa: BLE001 - one dead feed must not stop the others
            errors.append(f"{spec.type}: {str(e)[:160]}")
            continue
        for it in items:
            s, why = rank.score(conn, m.id, f"{it.title} {it.body}", m.interests)
            cur = conn.execute(
                """INSERT INTO items (module, ext_id, source, title, subtitle, body, url, data, score, why, published_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(module, ext_id) DO NOTHING""",
                (m.id, it.ext_id, spec.type, it.title, it.subtitle, it.body, it.url, json.dumps(it.data),
                 s, json.dumps(why), it.published),
            )  # fmt: skip
            added += cur.rowcount
    # keep the database small: beyond the best `keep` unseen items (and old skips), drop the text but
    # keep a tiny 'gone' row so the same item isn't fetched back in; forget those after 90 days
    conn.execute(
        """UPDATE items SET status = 'gone', body = NULL, subtitle = NULL, data = NULL, why = NULL
           WHERE module = ? AND ((status = 'new' AND id NOT IN (SELECT id FROM items WHERE module = ?
                 AND status = 'new' ORDER BY score DESC, id DESC LIMIT ?))
              OR (status = 'skipped' AND decided_at < datetime('now', '-30 days')))""",
        (m.id, m.id, m.keep),
    )
    conn.execute("DELETE FROM items WHERE module = ? AND status = 'gone' AND created_at < datetime('now', '-90 days')",
                 (m.id,))  # fmt: skip
    conn.execute(
        """INSERT INTO module_runs (module, last_run, last_error, added) VALUES (?, datetime('now'), ?, ?)
           ON CONFLICT(module) DO UPDATE SET last_run = excluded.last_run, last_error = excluded.last_error,
                                             added = excluded.added""",
        (m.id, "; ".join(errors) or None, added),
    )
    return {"added": added, "errors": errors}


def rescore(conn: sqlite3.Connection, m: Module) -> None:
    """Re-rank unseen items after the taste model learned something."""
    rows = conn.execute(
        "SELECT id, title, body FROM items WHERE module = ? AND status = 'new'", (m.id,)
    ).fetchall()
    for r in rows:
        sc, why = rank.score(conn, m.id, f"{r['title']} {r['body']}", m.interests)
        conn.execute("UPDATE items SET score = ?, why = ? WHERE id = ?", (sc, json.dumps(why), r["id"]))


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
    text = it["body"]
    if it["url"] and len(text) < 400:
        try:
            text = sources.read_page(it["url"])
        except Exception:  # noqa: BLE001 - fall back to what we have
            log.info("page read failed for %s", it["url"])
    out = brain.ask(
        f"Summarize this for a busy person.\nAbout them: {about}\n\nTitle: {it['title']}\n\n{text[:6000]}",
        SUMMARY_SCHEMA,
        light=True,
    )
    data["summary"] = out = {k: clean(v) for k, v in out.items()}
    conn.execute("UPDATE items SET data = ? WHERE id = ?", (json.dumps(data), item_id))
    return out
