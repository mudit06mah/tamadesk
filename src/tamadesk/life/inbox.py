"""Check the user's Gmail (IMAP, the same app password used for sending) for mail that belongs to
something they started: replies in their threads, bounces, and news from companies in their
pipeline ("thanks for applying", interview invites, rejections). Everything else is never stored.
"""

from __future__ import annotations

import email
import imaplib
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from tamadesk.core import db
from tamadesk.core.config import Settings
from tamadesk.life import mail, pipeline

KINDS = [  # first match wins; plain keyword rules, free and explainable
    ("rejected", re.compile(r"unfortunately|not (?:be )?moving forward|decided to (?:move|go) (?:forward )?with other|"
                            r"won'?t be (?:moving|proceeding)|position has been filled|not a fit at this time", re.IGNORECASE)),
    ("interview", re.compile(r"\binterview|schedule (?:a|some) (?:call|time|chat)|calendly\.com|next steps?\b|"
                             r"availability (?:for|this)|book a time", re.IGNORECASE)),
    ("applied", re.compile(r"thank(?:s| you) for (?:your )?appl|application (?:has been )?received|"
                           r"we(?:'ve| have) received your application|successfully applied", re.IGNORECASE)),
]  # fmt: skip
ATS_SENDERS = re.compile(
    r"greenhouse|ashbyhq|lever\.co|workable|smartrecruiters|bamboohr|recruitee|teamtailor", re.IGNORECASE
)


def classify(text: str, default: str = "update") -> str:
    return next((k for k, rx in KINDS if rx.search(text)), default)


def _h(msg, name: str) -> str:
    v = msg.get(name)
    return str(make_header(decode_header(v))) if v else ""


def _body(msg) -> str:
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"), None)
    if part is None:
        part = next((p for p in msg.walk() if p.get_content_type() == "text/html"), None)
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", "replace")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.split(r"\n\s*On .{5,120}wrote:\s*\n|\n-{2,}\s*Original Message", text)[
        0
    ]  # drop the quoted thread
    return re.sub(r"\s+", " ", text).strip()


def _stem(host: str) -> str:
    parts = host.lower().removeprefix("www.").split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


# sites that host other people's things: a kept video or repo there says nothing about who'd email you
PLATFORMS = {"youtube", "youtu", "github", "google", "medium", "substack", "notion", "linkedin", "twitter",
             "ycombinator", "wikipedia", "reddit", "arxiv", "mailchimp", "wellfound", "indeed"}  # fmt: skip


def pipeline_keys(conn: sqlite3.Connection) -> list[tuple[int, set[str]]]:
    """For each job/lead you're pursuing, the words that would identify mail about it.
    Only things you could hear back from: items with a stage, or kept jobs and leads."""
    import json

    out = []
    for r in conn.execute(
        """SELECT id, title, url, data FROM items WHERE stage IS NOT NULL OR (status = 'saved'
           AND (data LIKE '%"apply_url"%' OR data LIKE '%"email"%' OR module LIKE '%lead%'))"""
    ):
        d = json.loads(r["data"] or "{}")
        keys = set()
        for u in (r["url"] or "", d.get("apply_url") or ""):
            if "//" in u:
                host = u.split("/")[2]
                if ATS_SENDERS.search(host):  # jobs.ashbyhq.com/acme/... -> acme
                    seg = u.split("/")[3:4]
                    keys |= {seg[0].lower()} if seg else set()
                else:
                    keys.add(_stem(host))
        if d.get("company"):
            keys.add(re.sub(r"[^a-z0-9]", "", d["company"].lower()))
        out.append((r["id"], {k for k in keys if len(k) >= 4 and k not in PLATFORMS}))
    return out


def match(conn: sqlite3.Connection, me: str, msg) -> dict | None:
    """What a message is about, or None if it doesn't belong to anything the user started."""
    sender_name, sender = parseaddr(_h(msg, "From"))
    if sender.lower() == me.lower():
        return None
    refs = set(re.findall(r"<[^>]+>", f"{_h(msg, 'In-Reply-To')} {_h(msg, 'References')}"))
    subject, text = _h(msg, "Subject"), _body(msg)
    if refs:
        marks = ",".join("?" * len(refs))
        d = conn.execute(f"SELECT id, item_id FROM drafts WHERE message_id IN ({marks}) ORDER BY id DESC",
                         tuple(refs)).fetchone()  # fmt: skip
        if d:
            bounce = re.search(r"mailer-daemon|postmaster", sender, re.IGNORECASE)
            kind = "bounce" if bounce else classify(f"{subject} {text}", "reply")
            return {"draft_id": d["id"], "item_id": d["item_id"], "kind": kind, "from_addr": sender,
                    "from_name": sender_name, "subject": subject, "snippet": text[:600]}  # fmt: skip
    hay = f"{sender} {sender_name} {subject} {text[:400]}".lower()
    sender_stem = _stem(sender.split("@")[-1]) if "@" in sender else ""
    for item_id, keys in pipeline_keys(conn):
        if sender_stem in keys or any(re.search(rf"\b{re.escape(k)}\b", hay) for k in keys):
            kind = classify(f"{subject} {text}")
            if kind == "update" and not (sender_stem in keys):
                return None  # a passing mention in some newsletter isn't news about your application
            return {"draft_id": None, "item_id": item_id, "kind": kind, "from_addr": sender,
                    "from_name": sender_name, "subject": subject, "snippet": text[:600]}  # fmt: skip
    return None


STAGE_FOR = {"reply": "replied", "applied": "applied", "interview": "interview", "rejected": "rejected"}


def record(conn: sqlite3.Connection, message_id: str, m: dict, received: str) -> bool:
    with db.transaction(conn):
        cur = conn.execute(
            """INSERT INTO inbox (message_id, draft_id, item_id, kind, from_addr, from_name, subject, snippet, received_at)
               VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(message_id) DO NOTHING""",
            (message_id, m["draft_id"], m["item_id"], m["kind"], m["from_addr"], m["from_name"], m["subject"],
             m["snippet"], received),
        )  # fmt: skip
        if not cur.rowcount:
            return False
        if stage := STAGE_FOR.get(m["kind"]):
            pipeline.set_stage(conn, m["item_id"], stage, why=f"mail from {m['from_name'] or m['from_addr']}")
        db.event(
            conn,
            f"mail_{m['kind']}",
            ref_id=cur.lastrowid,
            detail=f"{m['from_name'] or m['from_addr']}: {m['subject']}",
        )
    return True


def check(s: Settings, conn: sqlite3.Connection, *, connect=imaplib.IMAP4_SSL) -> list[dict]:
    """Look at recent mail once. Returns what was new and matched (for notifications)."""
    if not mail.ready(s):
        return []
    since = db.get_profile(conn, "inbox_since") or (datetime.now(UTC) - timedelta(days=14)).strftime(
        "%d-%b-%Y"
    )
    found = []
    with connect("imap.gmail.com", 993) as imap:
        imap.login(s.mail.address, mail.get_secret(s, "gmail_app_password").replace(" ", ""))
        imap.select("INBOX", readonly=True)
        _, ids = imap.search(None, "SINCE", since)
        for num in ids[0].split()[-150:]:
            _, data = imap.fetch(num, "(BODY.PEEK[])")
            raw = next((x[1] for x in data if isinstance(x, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            mid = _h(msg, "Message-ID").strip()
            if not mid or conn.execute("SELECT 1 FROM inbox WHERE message_id = ?", (mid,)).fetchone():
                continue
            if (m := match(conn, s.mail.address, msg)) is None:
                continue
            try:
                received = (
                    parsedate_to_datetime(_h(msg, "Date")).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
                )
            except (TypeError, ValueError):
                received = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            if record(conn, mid, m, received):
                found.append(m)
    db.set_profile(conn, "inbox_since", (datetime.now(UTC) - timedelta(days=2)).strftime("%d-%b-%Y"))
    return found
