"""Sending a Mail draft through Gmail SMTP with an app password. Nothing sends without a click.

The password lives in <home>/secrets.json (mode 0600) and is never returned by the API.
Dry run (the default) delivers every email to the user's own address instead.
"""

from __future__ import annotations

import json
import smtplib
import sqlite3
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from tamadesk.core import db
from tamadesk.core.config import Settings

OPT_OUT = "If this isn't relevant, just say so and I won't follow up."


class MailError(RuntimeError):
    pass


def secrets_path(s: Settings):
    return s.home / "secrets.json"


def get_secret(s: Settings, key: str) -> str:
    try:
        return json.loads(secrets_path(s).read_text()).get(key, "")
    except (OSError, ValueError):
        return ""


def set_secret(s: Settings, key: str, value: str) -> None:
    p = secrets_path(s)
    data = json.loads(p.read_text()) if p.exists() else {}
    data[key] = value
    p.touch(mode=0o600, exist_ok=True)
    p.chmod(0o600)
    p.write_text(json.dumps(data))


def ready(s: Settings) -> bool:
    return bool(s.mail.address and get_secret(s, "gmail_app_password"))


def sent_today(conn: sqlite3.Connection) -> int:
    from tamadesk.api.routes import day_start_utc

    return conn.execute(
        "SELECT count(*) FROM drafts WHERE status = 'sent' AND sent_at >= ?", (day_start_utc(),)
    ).fetchone()[0]


def build(s: Settings, d: sqlite3.Row) -> EmailMessage:
    body = d["body"].rstrip()
    if d["item_id"] and OPT_OUT not in body:  # outreach to a lead: always offer a way out
        body += f"\n\n{OPT_OUT}"
    to = d["to_email"] if not s.mail.dry_run else s.mail.address
    m = EmailMessage()
    m["From"] = formataddr((s.mail.from_name, s.mail.address))
    m["To"] = formataddr((d["to_name"] or "", to))
    m["Subject"] = ("[dry run → " + d["to_email"] + "] " if s.mail.dry_run else "") + d["subject"]
    m["Message-ID"] = make_msgid(domain=s.mail.address.split("@")[-1])
    m.set_content(body)
    return m


def send(s: Settings, conn: sqlite3.Connection, draft_id: int, *, verified: bool) -> dict:
    d = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if d is None or d["status"] != "draft":
        raise MailError("this draft isn't waiting to be sent")
    if not ready(s):
        raise MailError("connect Gmail first (Mail → setup)")
    if "@" not in (d["to_email"] or ""):
        raise MailError("add a recipient address")
    if not d["email_sure"] and not verified:
        raise MailError("this address was guessed: check it yourself and tick 'I checked this address'")
    if sent_today(conn) >= s.mail.daily_cap:
        raise MailError(f"daily cap of {s.mail.daily_cap} emails reached")
    msg = build(s, d)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(s.mail.address, get_secret(s, "gmail_app_password").replace(" ", ""))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        conn.execute("UPDATE drafts SET error = ? WHERE id = ?", (str(e)[:300], draft_id))
        raise MailError(f"Gmail said: {e}") from e
    with db.transaction(conn):
        conn.execute(
            "UPDATE drafts SET status = 'sent', sent_at = datetime('now'), error = NULL WHERE id = ?",
            (draft_id,),
        )
        db.event(conn, "mail_sent", ref_id=draft_id, detail=d["subject"], xp=0 if s.mail.dry_run else 5)
    return {"dry_run": s.mail.dry_run, "to": msg["To"]}
