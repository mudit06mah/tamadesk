"""Token/cost accounting for every Claude call, so the user can see and cap what the assistant uses.

Claude Code reports `total_cost_usd` for each run. On a subscription that's an API-equivalent
figure, which makes it a fair yardstick for "how much did that use"."""

from __future__ import annotations

import sqlite3

from tamadesk.core import db
from tamadesk.core.config import Settings


def tokens_of(raw: dict) -> int:
    """Tokens a `claude -p` result used (input, output, and cache writes)."""
    u = raw.get("usage") or {}
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens"))


def record(s: Settings, kind: str, raw: dict) -> None:
    """Log one Claude call's cost and tokens, for Settings and the daily budget."""
    conn = db.connect(s.db_path)
    try:
        conn.execute("INSERT INTO usage (kind, cost_usd, tokens) VALUES (?, ?, ?)",
                     (kind, float(raw.get("total_cost_usd") or 0), tokens_of(raw)))  # fmt: skip
    finally:
        conn.close()


def today(conn: sqlite3.Connection) -> dict:
    """Today's spend so far: dollars (API-equivalent), tokens and runs."""
    from tamadesk.api.routes import day_start_utc

    r = conn.execute("SELECT coalesce(sum(cost_usd), 0), coalesce(sum(tokens), 0), count(*) FROM usage WHERE at >= ?",
                     (day_start_utc(),)).fetchone()  # fmt: skip
    return {"usd": round(r[0], 4), "tokens": r[1], "runs": r[2]}
