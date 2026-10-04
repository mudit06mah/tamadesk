"""Up next: the few things waiting on the user, gathered from every journey, each with one action.

Replies to answer, interviews to schedule, bounced addresses, follow-ups due, drafts waiting to be
sent, and jobs/leads kept but never acted on. Computed on demand from the database, so it can't
drift out of date.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

FOLLOWUP_AFTER = 4  # business days without a reply
MAX_FOLLOWUPS = 2


def business_days_since(ts: str, now: datetime | None = None) -> int:
    start = datetime.fromisoformat(ts).replace(tzinfo=UTC).date()
    end = (now or datetime.now(UTC)).date()
    return sum(1 for i in range(1, (end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5)


def followups_due(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    """The latest sent mail of each thread that nobody answered, old enough to nudge."""
    rows = conn.execute(
        """SELECT d.*, (SELECT count(*) FROM drafts f WHERE f.parent_id = d.id) AS children,
                  (SELECT count(*) FROM drafts a WHERE a.kind = 'followup' AND a.item_id = d.item_id
                     AND d.item_id IS NOT NULL AND a.status = 'sent') AS followups
           FROM drafts d WHERE d.status = 'sent' AND d.followup_off = 0 AND d.kind IN ('first', 'followup')
             AND d.message_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.draft_id = d.id AND i.kind != 'bounce')
             AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.item_id = d.item_id AND d.item_id IS NOT NULL
                             AND i.kind IN ('reply', 'interview', 'rejected'))"""
    ).fetchall()
    return [dict(r) | {"days": business_days_since(r["sent_at"], now)} for r in rows
            if r["children"] == 0 and r["followups"] < MAX_FOLLOWUPS
            and business_days_since(r["sent_at"], now) >= FOLLOWUP_AFTER]  # fmt: skip


def up_next(conn: sqlite3.Connection) -> list[dict]:
    out: list[dict] = []
    who = lambda r: r["from_name"] or r["from_addr"]
    for r in conn.execute("SELECT * FROM inbox WHERE status = 'new' ORDER BY id DESC"):
        title = {
            "reply": f"{who(r)} replied", "interview": f"{who(r)} wants to talk", "bounce": "An email bounced",
            "applied": f"{who(r)} got your application", "rejected": f"{who(r)} passed",
            "update": f"News from {who(r)}",
        }[r["kind"]]  # fmt: skip
        act = "answer" if r["kind"] in ("reply", "interview") else "seen"
        out.append({"kind": r["kind"], "id": r["id"], "title": title, "detail": r["subject"] or "",
                    "snippet": r["snippet"] or "", "draft_id": r["draft_id"], "action": act,
                    "from": f"{r['from_name'] or ''} <{r['from_addr']}>".strip(),
                    "rank": {"interview": 0, "reply": 1, "bounce": 2}.get(r["kind"], 5)})  # fmt: skip
    for d in followups_due(conn):
        out.append({"kind": "followup", "id": d["id"], "title": f"No reply from {d['to_name'] or d['to_email']}",
                    "detail": f"{d['subject']} · {d['days']} work days ago", "action": "followup", "rank": 3})  # fmt: skip
    waiting = conn.execute("SELECT count(*) FROM drafts WHERE status = 'draft'").fetchone()[0]
    if waiting:
        out.append({"kind": "drafts", "id": 0, "title": f"{waiting} draft{'s' if waiting > 1 else ''} waiting in Mail",
                    "detail": "read, tweak, send", "action": "mail", "rank": 4})  # fmt: skip
    for r in conn.execute(
        """SELECT module, count(*) AS n FROM items WHERE status = 'saved' AND stage IS NULL
           AND decided_at < datetime('now', '-2 days') AND (data LIKE '%apply_url%' OR module LIKE '%lead%')
           GROUP BY module"""
    ):
        out.append({"kind": "kept", "id": 0, "module": r["module"], "title": f"{r['n']} kept, not acted on yet",
                    "detail": "apply or email them before they go stale", "action": "tab", "rank": 6})  # fmt: skip
    return sorted(out, key=lambda x: x["rank"])
