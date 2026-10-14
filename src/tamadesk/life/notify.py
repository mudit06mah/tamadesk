"""Notifications with manners: what's urgent rings now, the rest waits for a good moment.

Reminders you set, meeting alerts, deadlines within the hour and a finished focus session always
ring. Everything else (tab updates, inbox news, early deadline nudges, the recap) waits during
quiet hours or while you focus, then arrives as one "while you were away" summary. Tab updates
are always batched, so five tabs refreshing don't mean five pings.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
from datetime import datetime

from tamadesk.core.config import Settings

log = logging.getLogger("tamadesk")
URGENT = {"reminder", "meeting", "deadline_now", "focus"}
BATCHED = {"tab"}


def desktop(title: str, body: str) -> None:
    """Best-effort desktop notification: Linux notify-send, macOS osascript, Windows toast."""
    try:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "tamadesk", title, body], timeout=5, check=False)
        elif shutil.which("osascript"):
            script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], timeout=5, check=False)
        elif shutil.which("powershell"):
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", _toast(title, body)], timeout=10, check=False
            )
    except (OSError, subprocess.SubprocessError):
        log.warning("desktop notification failed")


def _toast(title: str, body: str) -> str:
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace("'", "''")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]"
        "|Out-Null;$x=[Windows.Data.Xml.Dom.XmlDocument]::new();"
        f'$x.LoadXml(\'<toast><visual><binding template="ToastGeneric"><text>{esc(title)}</text>'
        f"<text>{esc(body)}</text></binding></visual></toast>');"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('tamadesk')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($x))"
    )


def quiet(s: Settings, now: datetime | None = None) -> bool:
    """Inside the user's quiet hours (local), which may wrap midnight (22 -> 8)."""
    a, b = s.day.quiet_start, s.day.quiet_end
    if a is None or b is None or a == b:
        return False
    h = (now or datetime.now().astimezone()).hour
    return a <= h < b if a < b else (h >= a or h < b)


def held(s: Settings, conn: sqlite3.Connection, now: datetime | None = None) -> str | None:
    """Why non-urgent pings should wait right now, or None."""
    if quiet(s, now):
        return "quiet hours"
    if conn.execute("SELECT 1 FROM focus WHERE status = 'running'").fetchone():
        return "focus"
    return None


def ping(s: Settings, conn: sqlite3.Connection, kind: str, title: str, body: str, *, send=desktop) -> bool:
    """Ring now, or hold it for later. Returns whether it rang."""
    if kind in URGENT or (kind not in BATCHED and not held(s, conn)):
        send(title, body)
        return True
    conn.execute("INSERT INTO pings (kind, title, body) VALUES (?, ?, ?)", (kind, title, body))
    return False


def flush(s: Settings, conn: sqlite3.Connection, *, send=desktop) -> int:
    """Deliver what waited, as one notification, once it's a good moment. Returns how many it held."""
    if held(s, conn):
        return 0
    rows = conn.execute("SELECT * FROM pings ORDER BY id").fetchall()
    if not rows:
        return 0
    if len(rows) == 1:
        send(rows[0]["title"], rows[0]["body"])
    else:
        parts = [f"{r['title']}: {r['body']}" for r in rows[:3]]
        more = f" (+{len(rows) - 3} more)" if len(rows) > 3 else ""
        send(f"While you were away: {len(rows)} updates", " · ".join(parts) + more)
    conn.execute("DELETE FROM pings WHERE id <= ?", (rows[-1]["id"],))
    return len(rows)
