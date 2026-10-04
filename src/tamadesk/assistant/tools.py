"""The tools the assistant can use on the user's desk (served over MCP by `assistant.mcp`).

Each tool is a plain function plus a JSON schema. They reuse the same code as the HTTP API, so
anything Bolt does is exactly what the buttons do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from tamadesk.core import db
from tamadesk.core.config import Settings
from tamadesk.core.net import fetch, get_json
from tamadesk.life import actions, capture
from tamadesk.modules import rank, sources, spec

FEEDS = sorted(k for k in sources.SOURCES if k != "agent")
TOOLS: dict[str, tuple[str, dict, Callable]] = {}


def tool(name: str, description: str, props: dict, required: list[str] | None = None):
    schema = {"type": "object", "properties": props, "required": required or list(props)}

    def reg(fn):
        TOOLS[name] = (description, schema, fn)
        return fn

    return reg


S = {"type": "string"}


def _short(it: sources.Item) -> dict:
    return {"title": it.title, "url": it.url, "subtitle": it.subtitle, "body": it.body[:300]}


@tool("search", f"Search a free source and get items back. sources: {', '.join(FEEDS)}. params by source: "
      "arxiv {query: comma-separated topics}; hn {query}; github {query: GitHub search syntax e.g. "
      "'topic:pixel-art language:python stars:>20', OR allowed between alternatives, days}; rss {url}; "
      "exa {query: describe the ideal page, 'category:company …' for companies}.",
      {"source": {"enum": FEEDS}, "params": {"type": "object"}, "limit": {"type": "integer"}}, ["source", "params"])  # fmt: skip
def search(s: Settings, conn: sqlite3.Connection, source: str, params: dict, limit: int = 8) -> list[dict]:
    params = dict(params) | ({"limit": limit} if source != "rss" else {})
    return [_short(it) for it in sources.fetch({"type": source, **params})[:limit]]


@tool("read_page", "Read a web page as plain text (Jina Reader). Use sparingly: pages are long.", {"url": S})
def read_page(s: Settings, conn: sqlite3.Connection, url: str) -> str:
    return sources.read_page(url, 6000)


@tool("list_tabs", "The user's tabs (modules) with their sources and item counts.", {}, [])
def list_tabs(s: Settings, conn: sqlite3.Connection) -> list[dict]:
    counts = {
        (r[0], r[1]): r[2] for r in conn.execute("SELECT module, status, count(*) FROM items GROUP BY 1, 2")
    }
    return [{"id": m.id, "name": m.name, "view": m.view, "every": m.every, "sources": [x.model_dump() for x in m.sources],
             "new": counts.get((m.id, "new"), 0), "kept": counts.get((m.id, "saved"), 0)} for m in spec.load_all(s)]  # fmt: skip


@tool("create_tab", "Create a tab that refreshes on its own. Prefer several precise sources over one vague one. "
      "Use source type 'agent' {task} only when no feed/search can express the need (it costs tokens per run). "
      "icon: book|news|code|target|eye|play|pen|star. view: feed (list) or deck (swipe, good for leads). "
      "every: 30m|6h|7d|'daily HH:MM'. actions from: save, skip, open, summarize, todo, draft.",
      {"name": S, "icon": S, "view": {"enum": ["feed", "deck"]}, "every": S,
       "sources": {"type": "array", "items": {"type": "object"}}, "interests": {"type": "array", "items": S},
       "actions": {"type": "array", "items": S}, "reasons": {"type": "array", "items": S}},
      ["name", "sources"])  # fmt: skip
def create_tab(s: Settings, conn: sqlite3.Connection, **kw) -> dict:
    m = spec.Module(**{"id": spec.slug(kw["name"])} | kw)  # validated here, so errors come back to the model
    # the desk's own API installs it, so the running scheduler picks it up and fills it now
    return get_json(
        f"http://{s.server.host}:{s.server.port}/api/modules/spec", body=m.model_dump(), timeout=15
    )


@tool(
    "delete_tab", "Delete one of the user's tabs and its items. Only when the user asked for it.", {"tab": S}
)
def delete_tab(s: Settings, conn: sqlite3.Connection, tab: str) -> str:
    if spec.get(s, tab) is None:
        return f"no tab {tab!r}"
    fetch(f"http://{s.server.host}:{s.server.port}/api/modules/{tab}", method="DELETE", timeout=15)
    return f"deleted {tab}"


@tool("add_to_tab", "Put items you found into a tab, e.g. the best results of a one-off search.",
      {"tab": S, "items": {"type": "array", "items": {"type": "object", "properties":
       {"title": S, "url": S, "subtitle": S, "body": S}, "required": ["title"]}}})  # fmt: skip
def add_to_tab(s: Settings, conn: sqlite3.Connection, tab: str, items: list[dict]) -> str:
    m = spec.get(s, tab)
    if m is None:
        return f"no tab {tab!r}; create it first"
    n = 0
    for i in items:
        sc, why = rank.score(conn, m.id, f"{i['title']} {i.get('body', '')}", m.interests)
        n += conn.execute(
            """INSERT INTO items (module, ext_id, source, title, subtitle, body, url, score, why)
               VALUES (?, ?, 'bolt', ?, ?, ?, ?, ?, ?) ON CONFLICT(module, ext_id) DO NOTHING""",
            (m.id, sources.uid(i.get("url") or i["title"]), i["title"], i.get("subtitle", ""), i.get("body", ""),
             i.get("url", ""), sc + 1, json.dumps(why)),
        ).rowcount  # fmt: skip
    return f"added {n} item(s) to {m.name}"


@tool("tab_items", "Read items from a tab (status new or saved).",
      {"tab": S, "status": {"enum": ["new", "saved"]}, "limit": {"type": "integer"}}, ["tab"])  # fmt: skip
def tab_items(
    s: Settings, conn: sqlite3.Connection, tab: str, status: str = "new", limit: int = 10
) -> list[dict]:
    rows = conn.execute("SELECT id, title, url, subtitle, body FROM items WHERE module = ? AND status = ? "
                        "ORDER BY score DESC LIMIT ?", (tab, status, limit)).fetchall()  # fmt: skip
    return [dict(r) | {"body": (r["body"] or "")[:200]} for r in rows]


@tool(
    "add_todo",
    "Add a todo. `due` is optional natural language ('friday 5pm').",
    {"title": S, "due": S},
    ["title"],
)
def add_todo(s: Settings, conn: sqlite3.Connection, title: str, due: str = "") -> str:
    c = capture.parse(f"todo {title} {due}".strip())
    with db.transaction(conn):
        actions.add_todo(conn, c.text, capture.sql_ts(c.due_at) if c.due_at else None)
    return "added" + (f", due {c.due_at:%a %H:%M} UTC" if c.due_at else "")


@tool("set_reminder", "Ring the user at a time ('in 20 min', 'tomorrow 9am').", {"text": S, "when": S})
def set_reminder(s: Settings, conn: sqlite3.Connection, text: str, when: str) -> str:
    c = capture.parse(f"remind me to {text} {when}")
    if c.kind != "reminder":
        return f"couldn't understand the time {when!r}"
    with db.transaction(conn):
        actions.add_reminder(conn, c.text, capture.sql_ts(c.due_at))
    return f"reminder set for {c.due_at:%a %d %b %H:%M} UTC"


@tool("log", "Add a line to the user's daily log.", {"text": S})
def log(s: Settings, conn: sqlite3.Connection, text: str) -> str:
    with db.transaction(conn):
        actions.add_log(conn, text)
    return "logged"


@tool("draft_email", "Save an email draft to the user's Mail tab for them to review and send. Never says it was "
      "sent. to_email must be published on a page you saw (email_source = that URL); if you guessed it, set "
      "email_sure false. item_id links a lead from a tab.",
      {"subject": S, "body": S, "to_name": S, "to_email": S, "email_source": S, "email_sure": {"type": "boolean"},
       "item_id": {"type": "integer"}}, ["subject", "body"])  # fmt: skip
def draft_email(s: Settings, conn: sqlite3.Connection, subject: str, body: str, **kw) -> str:
    from tamadesk.life.writer import clean

    with db.transaction(conn):
        rid = actions.add_draft(conn, ask="bolt", subject=clean(subject), body=clean(body), **kw)
    return f"draft #{rid} saved to Mail"


def call(s: Settings, name: str, args: dict) -> str:
    conn = db.connect(s.db_path)
    try:
        out = TOOLS[name][2](s, conn, **args)
    finally:
        conn.close()
    return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
