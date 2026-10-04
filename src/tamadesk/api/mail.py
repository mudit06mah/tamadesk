"""Mail API: drafts (written by the assistant or by hand), editing, sending, Gmail setup."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tamadesk.api.routes import Conn
from tamadesk.core.config import get_settings, save_settings
from tamadesk.life import mail
from tamadesk.life.actions import add_draft

router = APIRouter(prefix="/api/mail")


@router.get("")
def list_mail(conn: Conn, status: Literal["draft", "sent"] = "draft") -> dict:
    s = get_settings()
    order = "sent_at DESC" if status == "sent" else "id DESC"
    rows = conn.execute(
        f"SELECT * FROM drafts WHERE status = ? ORDER BY {order} LIMIT 50", (status,)
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
