"""Mail API: drafts (written by the assistant or by hand), editing, sending, Gmail setup."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tamadesk.api.routes import Conn
from tamadesk.assistant import runner
from tamadesk.core import db
from tamadesk.core.config import get_settings, save_settings
from tamadesk.life import inbox, mail
from tamadesk.life.actions import add_draft
from tamadesk.life.writer import clean

router = APIRouter(prefix="/api/mail")


@router.get("")
def list_mail(conn: Conn, status: Literal["draft", "sent"] = "draft") -> dict:
    s = get_settings()
    order = "sent_at DESC" if status == "sent" else "id DESC"
    # each draft says what it's for (the item) and, once sent, what came back (the latest inbox match)
    rows = conn.execute(
        f"""SELECT d.*, i.title AS item_title, i.module AS item_module,
                   (SELECT kind FROM inbox n WHERE n.draft_id = d.id OR (n.item_id = d.item_id AND n.received_at >= d.sent_at)
                    ORDER BY n.id DESC LIMIT 1) AS heard
            FROM drafts d LEFT JOIN items i ON i.id = d.item_id
            WHERE d.status = ? ORDER BY {order} LIMIT 50""",
        (status,),
    ).fetchall()
    return {"items": [dict(r) for r in rows], "ready": mail.ready(s), "address": s.mail.address,
            "dry_run": s.mail.dry_run, "daily_cap": s.mail.daily_cap, "sent_today": mail.sent_today(conn)}  # fmt: skip


class DraftIn(BaseModel):
    subject: str = ""
    body: str = ""
    to_name: str = ""
    to_email: str = ""


@router.post("")
def new_draft(d: DraftIn, conn: Conn) -> dict:
    return {"id": add_draft(conn, ask="manual", **d.model_dump())}


@router.patch("/{draft_id}")
def edit(draft_id: int, d: DraftIn, conn: Conn) -> dict:
    row = conn.execute(
        "SELECT to_email FROM drafts WHERE id = ? AND status = 'draft'", (draft_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no such draft")
    # an address the user typed themselves counts as checked
    sure = 1 if d.to_email.strip().lower() != (row["to_email"] or "") else None
    conn.execute(
        """UPDATE drafts SET subject = ?, body = ?, to_name = ?, to_email = ?,
               email_sure = coalesce(?, email_sure) WHERE id = ?""",
        (d.subject, d.body, d.to_name, d.to_email.strip().lower(), sure, draft_id),
    )
    return {"ok": True}


class SendIn(BaseModel):
    verified: bool = False


@router.post("/{draft_id}/send")
def send(draft_id: int, b: SendIn, conn: Conn) -> dict:
    try:
        return mail.send(get_settings(), conn, draft_id, verified=b.verified)
    except mail.MailError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{draft_id}/drop")
def drop(draft_id: int, conn: Conn) -> dict:
    conn.execute("UPDATE drafts SET status = 'dropped' WHERE id = ? AND status = 'draft'", (draft_id,))
    return {"ok": True}


class RedraftIn(BaseModel):
    note: str = Field(min_length=2, max_length=1000)


REDRAFT_SCHEMA = {"type": "object", "required": ["subject", "body"],
                  "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}  # fmt: skip


@router.post("/{draft_id}/redraft")
def redraft(draft_id: int, b: RedraftIn, conn: Conn) -> dict:
    """Rewrite one draft from the user's note. The note is also kept as a standing writing rule."""
    d = conn.execute("SELECT * FROM drafts WHERE id = ? AND status = 'draft'", (draft_id,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such draft")
    s = get_settings()
    rules = (db.get_profile(conn, "writing_feedback", []) + [b.note.strip()])[-15:]
    db.set_profile(conn, "writing_feedback", rules)
    prompt = (f"Rewrite this email draft following the user's feedback. Keep what they didn't ask to change. "
              f"Use read_doc if it needs facts from their documents.\nFeedback: {b.note}\n\n"
              f"To: {d['to_name'] or ''} <{d['to_email'] or ''}>\nSubject: {d['subject']}\n\n{d['body']}")  # fmt: skip
    try:
        out = runner.structured(
            s, conn, prompt, REDRAFT_SCHEMA, kind="redraft", budget=s.assistant.max_usd_per_ask
        )
    except runner.BudgetError as e:
        raise HTTPException(429, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(502, f"redraft failed: {e}") from e
    subject, body = clean(out["subject"]), clean(out["body"])
    conn.execute("UPDATE drafts SET subject = ?, body = ? WHERE id = ?", (subject, body, draft_id))
    return {"subject": subject, "body": body}


@router.post("/{draft_id}/followup")
def followup(draft_id: int, conn: Conn) -> dict:
    """Write a short follow-up in the same thread (lands in Mail as a draft, nothing is sent)."""
    d = conn.execute("SELECT * FROM drafts WHERE id = ? AND status = 'sent'", (draft_id,)).fetchone()
    if d is None:
        raise HTTPException(404, "no such sent email")
    s = get_settings()
    prompt = (f"Write a short, friendly follow-up to this email that got no reply. Add one new useful thing if "
              f"you can (read my documents with read_doc if helpful); 3-5 sentences, no guilt-tripping.\n\n"
              f"Sent {d['sent_at']} to {d['to_name'] or ''} <{d['to_email']}>\nSubject: {d['subject']}\n\n{d['body']}")  # fmt: skip
    try:
        out = runner.structured(
            s, conn, prompt, REDRAFT_SCHEMA, kind="followup", budget=s.assistant.max_usd_per_ask
        )
    except runner.BudgetError as e:
        raise HTTPException(429, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(502, f"couldn't write the follow-up: {e}") from e
    rid = add_draft(conn, ask="follow-up", subject=f"Re: {d['subject']}", body=clean(out["body"]),
                    parent_id=draft_id, kind="followup")  # fmt: skip
    return {"id": rid}


@router.post("/{draft_id}/no-followup")
def no_followup(draft_id: int, conn: Conn) -> dict:
    conn.execute("UPDATE drafts SET followup_off = 1 WHERE id = ?", (draft_id,))
    return {"ok": True}


@router.post("/inbox/check")
def check_inbox(conn: Conn) -> dict:
    try:
        return {"found": len(inbox.check(get_settings(), conn))}
    except (OSError, inbox.imaplib.IMAP4.error) as e:
        raise HTTPException(502, f"couldn't read the inbox: {e}") from e


@router.post("/inbox/{msg_id}/done")
def inbox_done(msg_id: int, conn: Conn) -> dict:
    conn.execute("UPDATE inbox SET status = 'done' WHERE id = ?", (msg_id,))
    return {"ok": True}


class Setup(BaseModel):
    address: str
    from_name: str = ""
    app_password: str = ""  # blank keeps the saved one
    dry_run: bool = True
    daily_cap: int = 20


@router.put("/setup")
def setup(b: Setup) -> dict:
    s = get_settings()
    s.mail.address, s.mail.from_name = b.address.strip(), b.from_name.strip()
    s.mail.dry_run, s.mail.daily_cap = b.dry_run, max(1, min(b.daily_cap, 200))
    save_settings(s)
    if b.app_password.strip():
        mail.set_secret(s, "gmail_app_password", b.app_password.strip())
    return {"ok": True, "ready": mail.ready(s)}
