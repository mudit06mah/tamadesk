"""YouTube without the algorithm or a login: search, a video's or playlist's details, and a description
you'd actually read. Through yt-dlp (agent-reach installs it), zero tokens.

Channel descriptions are mostly promo ("Help fund future projects: patreon…", "Enrollment link: …"),
so `blurb` keeps only the sentences that describe the video. `pick` chooses the few videos worth
watching for one topic of a learning roadmap: on-topic titles, real explainers (not Shorts, not
ten-hour streams), and what many people found useful.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
import subprocess

VIDEO = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})")
PLAYLIST = re.compile(r"youtube\.com/(?:playlist\?|watch\?.*?)list=([\w-]+)")
URLISH = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|in|io|gg|ly|me|co|org|net)/", re.IGNORECASE)
PROMO = re.compile(
    r"patreon|sponsor|subscribe|join (?:this|my|our)|enrol|enroll|bootcamp|course link|discount|coupon|use code|"
    r"affiliate|merch|follow (?:me|us)|instagram|twitter|discord|telegram|whatsapp|linkedin|website|talk to|"
    r"book a|check out|buy |\bsupport\b(?! vector)|help fund|membership|links?\s*:|→|#\w+|timestamps|chapters|"
    r"in stock|posters?\b|\bshop\b|\bstore\b|your career|start your|free trial|sign up|newsletter|download (?:my|our|the)",
    re.IGNORECASE,
)
STAMP = re.compile(r"^\(?\d{1,2}:\d{2}")
WORD = re.compile(r"[a-z0-9]+")


def blurb(text: str, n: int = 240) -> str:
    """The sentences of a video description that say what it's about; no links, promo or timestamps."""
    keep = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        p = part.strip(" -–•*|")
        ok = len(p) > 15 and not p.endswith(":")  # "Welch Labs Posters:" labels a link that was cut off
        if ok and not URLISH.search(p) and not PROMO.search(p) and not STAMP.match(p):
            keep.append(p)
    out = " ".join(keep)
    return out if len(out) <= n else out[:n].rsplit(" ", 1)[0] + "…"


def thumb(video_id: str) -> str:
    """A video's medium thumbnail URL."""
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _ytdlp(args: list[str], timeout: int = 40) -> dict:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp isn't installed (agent-reach installs it, or: pipx install yt-dlp)")
    out = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", *args], capture_output=True,
                         text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)  # fmt: skip
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "yt-dlp failed").strip()[-200:])
    return json.loads(out.stdout or "{}")


def search(query: str, n: int = 10) -> list[dict]:
    """Videos for a query: [{id, title, channel, duration, views, description}]."""
    d = _ytdlp([f"ytsearch{n}:{query}"])
    return [
        {"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
         "duration": int(float(e["duration"])) if e.get("duration") else 0, "views": int(e.get("view_count") or 0),
         "description": e.get("description") or ""}
        for e in d.get("entries") or [] if e.get("id") and len(e["id"]) == 11
    ]  # fmt: skip


def details(url: str) -> dict | None:
    """A video's or playlist's channel, length, views, description and picture. None if not YouTube."""
    if not (VIDEO.search(url) or PLAYLIST.search(url)):
        return None
    d = _ytdlp(["--playlist-end", "1", url], timeout=30)
    first = (d.get("entries") or [{}])[0]
    vid = d.get("id") if VIDEO.search(url) else first.get("id")
    count = d.get("playlist_count") or len(d.get("entries") or [])
    return {
        "channel": d.get("channel") or d.get("uploader") or first.get("channel") or "",
        "duration": int(float(d["duration"])) if d.get("duration") else 0,
        "views": int(d.get("view_count") or 0),
        "description": blurb(d.get("description") or ""),
        "thumb": thumb(vid) if vid and len(vid) == 11 else "",
        "videos": count if d.get("_type") == "playlist" else 0,
    }


def views_text(n: int) -> str:
    """'6.3M', '820K' or the number."""
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else str(n)


def subtitle(v: dict) -> str:
    """'Channel · playlist of 10 videos · 1.2M views', whatever is known."""
    bits = [v.get("channel", "")]
    if v.get("videos"):
        bits.append(f"playlist of {v['videos']} videos")
    if v.get("views"):
        bits.append(f"{views_text(v['views'])} views")
    return " · ".join(b for b in bits if b)


def _words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if len(w) > 2}


def pick(videos: list[dict], topic: str, n: int = 3) -> list[dict]:
    """The best few for one topic: the title is about it, it's an explainer length, many found it useful."""
    want = _words(topic)

    def score(v: dict) -> float:
        on = len(want & _words(v["title"])) / max(1, len(want))
        d = v["duration"]
        length = -5 if 0 < d < 90 else (-1 if d > 3 * 3600 else 1 if 180 <= d <= 5400 else 0)
        return 3 * on + 0.6 * math.log10(v["views"] + 10) + length

    good = [v for v in videos if not (0 < v["duration"] < 90)]  # Shorts aren't for learning
    return sorted(good, key=score, reverse=True)[:n]


def fill(conn: sqlite3.Connection, module: str, limit: int = 8) -> int:
    """Give YouTube links in a tab (often added by Bolt with just a title) their channel, length,
    picture and description. Each link is tried once."""
    rows = conn.execute(
        """SELECT id, source, url, subtitle, body, data FROM items WHERE module = ? AND status IN ('new', 'saved', 'done')
           AND (url LIKE '%youtube.com/%' OR url LIKE '%youtu.be/%') AND coalesce(json_extract(data, '$.yt'), 0) = 0
           AND (source = 'bolt' OR coalesce(body, '') = '') LIMIT ?""",
        (module, limit),
    ).fetchall()  # fmt: skip
    done = 0
    for r in rows:
        data = json.loads(r["data"] or "{}") | {"yt": 1}
        try:
            v = details(r["url"])
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
            v = None
        if v:
            data |= {k: v[k] for k in ("thumb", "duration", "views") if v[k]}
            note = (
                (r["subtitle"] or "").strip() if r["source"] == "bolt" else ""
            )  # Bolt's line on why this one
            body = " ".join(x for x in [f"{note}." if note and not note.endswith(".") else note,
                                        v["description"]] if x) or r["body"]  # fmt: skip
            conn.execute("UPDATE items SET subtitle = ?, body = ?, data = ? WHERE id = ?",
                         (subtitle(v) or r["subtitle"], body, json.dumps(data), r["id"]))  # fmt: skip
            done += 1
        else:
            conn.execute("UPDATE items SET data = ? WHERE id = ?", (json.dumps(data), r["id"]))
    return done
