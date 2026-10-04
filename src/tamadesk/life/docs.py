"""The user's documents (resume, product brief, notes) as plain text the assistant can read."""

from __future__ import annotations

import base64
import io
import sqlite3

from pypdf import PdfReader

KINDS = ("resume", "product", "notes", "other")
MAX_CHARS = 60_000


def extract(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()
    return data.decode("utf-8", "replace").strip()


def add(conn: sqlite3.Connection, name: str, kind: str, data_b64: str) -> int:
    text = extract(name, base64.b64decode(data_b64))
    if len(text) < 20:
        raise ValueError("couldn't read any text from that file (scanned PDFs aren't supported yet)")
    return conn.execute("INSERT INTO docs (name, kind, text) VALUES (?, ?, ?)",
                        (name[:120], kind if kind in KINDS else "other", text[:MAX_CHARS])).lastrowid  # fmt: skip


def listing(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, kind, length(text) AS chars, created_at FROM docs ORDER BY id"
        )
    ]


def read(conn: sqlite3.Connection, ref: str) -> str | None:
    row = conn.execute("SELECT text FROM docs WHERE CAST(id AS TEXT) = ? OR name = ? OR kind = ? ORDER BY id DESC",
                       (str(ref), ref, ref)).fetchone()  # fmt: skip
    return row["text"] if row else None
