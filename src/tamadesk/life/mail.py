"""Sending a Mail draft through your mail provider's SMTP with an app password. Nothing sends
without a click. Gmail, Fastmail, iCloud, Outlook, Yahoo and Zoho are presets; anything else is a
custom host.

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
from tamadesk.life import pipeline

OPT_OUT = "If this isn't relevant, just say so and I won't follow up."
# provider: (IMAP host, SMTP host, SMTP port). 465 is SSL, 587 is STARTTLS.
PROVIDERS = {
    "gmail": ("imap.gmail.com", "smtp.gmail.com", 465),
    "fastmail": ("imap.fastmail.com", "smtp.fastmail.com", 465),
    "icloud": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "outlook": ("outlook.office365.com", "smtp.office365.com", 587),
    "yahoo": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", 465),
    "zoho": ("imap.zoho.com", "smtp.zoho.com", 465),
}


def hosts(s: Settings) -> tuple[str, str, int]:
    """(IMAP host, SMTP host, SMTP port) for the user's provider."""
    if s.mail.provider in PROVIDERS:
        return PROVIDERS[s.mail.provider]
    return s.mail.imap_host, s.mail.smtp_host, s.mail.smtp_port


def _smtp(s: Settings):
    _, host, port = hosts(s)
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=30)
    smtp = smtplib.SMTP(host, port, timeout=30)
    smtp.starttls()
    return smtp


class MailError(RuntimeError):
    """Something the user can fix before a send (no recipient, mail not connected, ...)."""


def secrets_path(s: Settings):
    """secrets.json in the data folder (0600, never exported)."""
    return s.home / "secrets.json"


def get_secret(s: Settings, key: str) -> str:
    """A value from secrets.json, '' if missing."""
    try:
        return json.loads(secrets_path(s).read_text()).get(key, "")
    except (OSError, ValueError):
        return ""


def set_secret(s: Settings, key: str, value: str) -> None:
    """Store a value in secrets.json, readable only by the user."""
    p = secrets_path(s)
    data = json.loads(p.read_text()) if p.exists() else {}
    data[key] = value
    p.touch(mode=0o600, exist_ok=True)
    p.chmod(0o600)
    p.write_text(json.dumps(data))


def ready(s: Settings) -> bool:
    """Is mail set up enough to send?"""
    return bool(s.mail.address and get_secret(s, "gmail_app_password"))


def sent_today(conn: sqlite3.Connection) -> int:
    """Mails sent today (there's a daily cap)."""
    from tamadesk.api.routes import day_start_utc

    return conn.execute(
        "SELECT count(*) FROM drafts WHERE status = 'sent' AND sent_at >= ?", (day_start_utc(),)
    ).fetchone()[0]


def build(s: Settings, d: sqlite3.Row, parent: sqlite3.Row | None = None) -> EmailMessage:
    """The email for a draft. Threads replies under their parent, adds an opt-out line to first outreach, and goes
    to yourself in dry-run mode."""
    body = d["body"].rstrip()
    if (
        d["item_id"] and d["kind"] == "first" and OPT_OUT not in body
    ):  # first outreach: always offer a way out
        body += f"\n\n{OPT_OUT}"
    to = d["to_email"] if not s.mail.dry_run else s.mail.address
    m = EmailMessage()
    m["From"] = formataddr((s.mail.from_name, s.mail.address))
    m["To"] = formataddr((d["to_name"] or "", to))
    subject = d["subject"]
    if parent is not None and not subject.lower().startswith("re:"):
        subject = f"Re: {parent['subject']}"
    m["Subject"] = ("[dry run → " + d["to_email"] + "] " if s.mail.dry_run else "") + subject
    m["Message-ID"] = make_msgid(domain=s.mail.address.split("@")[-1])
    if parent is not None and parent["message_id"]:  # follow-ups and replies stay in the same thread
        m["In-Reply-To"] = parent["message_id"]
        m["References"] = parent["message_id"]
    m.set_content(body)
    return m


def send(s: Settings, conn: sqlite3.Connection, draft_id: int, *, verified: bool) -> dict:
    """Send a draft over the user's own SMTP, only on their click. A guessed address must be confirmed (`verified`)."""
    d = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if d is None or d["status"] != "draft":
        raise MailError("this draft isn't waiting to be sent")
    if not ready(s):
        raise MailError("connect your mail first (Mail → setup)")
    if "@" not in (d["to_email"] or ""):
        raise MailError("add a recipient address")
    if not d["email_sure"] and not verified:
        raise MailError("this address was guessed: check it yourself and tick 'I checked this address'")
    if sent_today(conn) >= s.mail.daily_cap:
        raise MailError(f"daily cap of {s.mail.daily_cap} emails reached")
    parent = (
        conn.execute("SELECT * FROM drafts WHERE id = ?", (d["parent_id"],)).fetchone()
        if d["parent_id"]
        else None
    )
    msg = build(s, d, parent)
    try:
        with _smtp(s) as smtp:
            smtp.login(s.mail.address, get_secret(s, "gmail_app_password").replace(" ", ""))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        conn.execute("UPDATE drafts SET error = ? WHERE id = ?", (str(e)[:300], draft_id))
        raise MailError(f"your mail server said: {e}") from e
    with db.transaction(conn):
        conn.execute(
            "UPDATE drafts SET status = 'sent', sent_at = datetime('now'), error = NULL, message_id = ? WHERE id = ?",
            (msg["Message-ID"], draft_id),
        )
        pipeline.set_stage(conn, d["item_id"], "emailed", why=f"to {d['to_email']}")
        db.event(conn, "mail_sent", ref_id=draft_id, detail=d["subject"], xp=0 if s.mail.dry_run else 5)
    return {"dry_run": s.mail.dry_run, "to": msg["To"]}
