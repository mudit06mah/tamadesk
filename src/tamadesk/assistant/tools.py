"""The tools the assistant can use on the user's desk (served over MCP by `assistant.mcp`).

Each tool is a plain function plus a JSON schema. They reuse the same code as the HTTP API, so
anything Bolt does is exactly what the buttons do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from tamadesk.core import db
from tamadesk.core.config import Settings
from tamadesk.core.net import fetch, get_json
from tamadesk.life import actions, capture, docs, github, memory
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


def _local(utc_naive) -> str:
    return utc_naive.replace(tzinfo=UTC).astimezone().strftime("%a %d %b %H:%M")


def _local_ts(ts: str | None) -> str | None:
    return _local(datetime.fromisoformat(ts)) if ts else None


def _tab(s: Settings, ref: str) -> spec.Module | None:
    """A tab by id or by its display name."""
    return spec.get(s, ref) or next(
        (m for m in spec.load_all(s) if m.name.lower() == ref.strip().lower()), None
    )


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
    return [{"id": m.id, "name": m.name, "every": m.every, "sources": [x.model_dump() for x in m.sources],
             "new": counts.get((m.id, "new"), 0), "kept": counts.get((m.id, "saved"), 0)} for m in spec.load_all(s)]  # fmt: skip


@tool("create_tab", "Create a tab that refreshes on its own. Prefer several precise sources over one vague one. "
      "Use source type 'agent' {task} only when no feed/search can express the need (it costs tokens per run). "
      "icon: book|news|code|target|eye|play|pen|star. "
      "every: 30m|6h|7d|'daily HH:MM'. actions from: save, skip, open, summarize, todo, draft. "
      "notify: true pings the desktop when something new arrives (status pages, launches, releases).",
      {"name": S, "icon": S, "every": S,
       "sources": {"type": "array", "items": {"type": "object"}}, "interests": {"type": "array", "items": S},
       "actions": {"type": "array", "items": S}, "notify": {"type": "boolean"}},
      ["name", "sources"])  # fmt: skip
def create_tab(s: Settings, conn: sqlite3.Connection, **kw) -> dict | str:
    m = spec.Module(**{"id": spec.slug(kw["name"])} | kw)  # validated here, so errors come back to the model
    if problems := _broken(m):
        return "not created, these sources don't work, replace them and try again:\n" + "\n".join(problems)
    # the desk's own API installs it, so the running scheduler picks it up and fills it now
    return get_json(f"{_api(s)}/modules/spec", body=m.model_dump(), timeout=15)


@tool("update_tab", "Change an existing tab (by id or name): e.g. replace a broken source, change the schedule, "
      "interests or notify. Pass only the fields to change; 'sources' replaces the whole list.",
      {"tab": S, "name": S, "icon": S, "every": S, "sources": {"type": "array", "items": {"type": "object"}},
       "interests": {"type": "array", "items": S}, "actions": {"type": "array", "items": S},
       "notify": {"type": "boolean"}}, ["tab"])  # fmt: skip
def update_tab(s: Settings, conn: sqlite3.Connection, tab: str, **changes) -> dict | str:
    old = _tab(s, tab)
    if old is None:
        return f"no tab {tab!r}"
    m = spec.Module(**old.model_dump() | changes)
    if "sources" in changes and (problems := _broken(m)):
        return "not changed, these sources don't work, pick others:\n" + "\n".join(problems)
    fetch(f"{_api(s)}/modules/{m.id}/spec", body=m.model_dump(), method="PUT", timeout=15)
    return f"updated {m.name}; it's refreshing now"


def _api(s: Settings) -> str:
    return f"http://{s.server.host}:{s.server.port}/api"


def _broken(m: spec.Module) -> list[str]:
    """Try every source once, so a dead feed (401s, empty queries) is fixed now, not found later."""
    problems = []
    for src in m.sources:
        if src.type == "agent":
            continue  # costs tokens on every run; trust it
        try:
            if not sources.fetch(src.model_dump()):
                problems.append(f"{src.model_dump()} returned nothing")
        except Exception as e:  # noqa: BLE001 - reported back so the model can pick another source
            problems.append(f"{src.model_dump()} failed: {str(e)[:160]}")
    return problems


@tool(
    "delete_tab", "Delete one of the user's tabs and its items. Only when the user asked for it.", {"tab": S}
)
def delete_tab(s: Settings, conn: sqlite3.Connection, tab: str) -> str:
    if spec.get(s, tab) is None:
        return f"no tab {tab!r}"
    fetch(f"{_api(s)}/modules/{tab}", method="DELETE", timeout=15)
    return f"deleted {tab}"


@tool("add_to_tab", "Put items you found into a tab, e.g. the best results of a one-off search.",
      {"tab": S, "items": {"type": "array", "items": {"type": "object", "properties":
       {"title": S, "url": S, "subtitle": S, "body": S}, "required": ["title"]}}})  # fmt: skip
def add_to_tab(s: Settings, conn: sqlite3.Connection, tab: str, items: list[dict]) -> str:
    m = _tab(s, tab)
    if m is None:
        return f"no tab {tab!r}; create it first"
    n = 0
    for i in items:
        sc, why = rank.score(conn, m.id, f"{i['title']} {i.get('body', '')}", m.interests)
        n += conn.execute(
            """INSERT INTO items (module, ext_id, source, title, subtitle, body, url, score, why)
               SELECT ?, ?, 'bolt', ?, ?, ?, ?, ?, ? WHERE NOT EXISTS
                   (SELECT 1 FROM items WHERE module = ?1 AND url = ?6 AND url != '')
               ON CONFLICT(module, ext_id) DO NOTHING""",
            (m.id, sources.uid(i.get("url") or i["title"]), i["title"], i.get("subtitle", ""), i.get("body", ""),
             i.get("url", ""), sc + 1, json.dumps(why)),
        ).rowcount  # fmt: skip
    return f"added {n} item(s) to {m.name}"


@tool("tab_items", "Read items from a tab (status new or saved).",
      {"tab": S, "status": {"enum": ["new", "saved"]}, "limit": {"type": "integer"}}, ["tab"])  # fmt: skip
def tab_items(
    s: Settings, conn: sqlite3.Connection, tab: str, status: str = "new", limit: int = 10
) -> list[dict] | str:
    m = _tab(s, tab)
    if m is None:
        return f"no tab {tab!r}"
    rows = conn.execute("SELECT id, title, url, subtitle, body FROM items WHERE module = ? AND status = ? "
                        "ORDER BY score DESC LIMIT ?", (m.id, status, limit)).fetchall()  # fmt: skip
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
    return "added" + (f", due {_local(c.due_at)}" if c.due_at else "")


@tool("list_todos", "The user's open todos (with due times) and what they finished today.", {}, [])
def list_todos(s: Settings, conn: sqlite3.Connection) -> dict:
    from tamadesk.api.routes import day_start_utc

    open_ = conn.execute(
        "SELECT id, title, due_at FROM todos WHERE status = 'open' ORDER BY due_at IS NULL, due_at, id"
    )
    done = conn.execute(
        "SELECT id, title FROM todos WHERE status = 'done' AND done_at >= ?", (day_start_utc(),)
    )
    return {
        "open": [dict(r) | {"due": _local_ts(r["due_at"])} for r in open_],
        "done_today": [dict(r) for r in done],
    }


@tool("complete_todo", "Mark one of the user's todos done (by id from list_todos), when they say they finished it.",
      {"id": {"type": "integer"}})  # fmt: skip
def complete_todo(s: Settings, conn: sqlite3.Connection, id: int) -> str:
    return "done" if actions.complete_todo(conn, id) else f"no open todo #{id}"


@tool("set_reminder", "Ring the user at a time ('in 20 min', 'tomorrow 9am').", {"text": S, "when": S})
def set_reminder(s: Settings, conn: sqlite3.Connection, text: str, when: str) -> str:
    c = capture.parse(f"remind me to {text} {when}")
    if c.kind != "reminder":
        return f"couldn't understand the time {when!r}"
    with db.transaction(conn):
        actions.add_reminder(conn, c.text, capture.sql_ts(c.due_at))
    return f"reminder set for {_local(c.due_at)} (the user's local time)"


@tool("log", "Add a line to the user's daily log.", {"text": S})
def log(s: Settings, conn: sqlite3.Connection, text: str) -> str:
    with db.transaction(conn):
        actions.add_log(conn, text)
    return "logged"


@tool("recall", "Search the user's memory: every past chat, log line, todo, email and saved item, plus daily "
      "digests and facts. For questions about the past ('what was that…', 'when did I…'). Search with several "
      "alternative words and broader categories at once (e.g. 'japanese dish food sushi ramen restaurant'); "
      "dates are YYYY-MM-DD.",
      {"query": S, "since": S, "until": S}, ["query"])  # fmt: skip
def recall(s: Settings, conn: sqlite3.Connection, query: str, since: str = "", until: str = "") -> list[dict]:
    memory.sync_files(s, conn)
    return memory.search(conn, query, since=since, until=until)


@tool("day_notes", "Everything from one day (YYYY-MM-DD): its digest, facts and raw history.", {"day": S})
def day_notes(s: Settings, conn: sqlite3.Connection, day: str) -> dict:
    memory.sync_files(s, conn)
    return memory.day_notes(conn, day)


@tool(
    "read_doc",
    "Read one of the user's documents (resume, product brief, notes) by name, id or kind.",
    {"ref": S},
)
def read_doc(s: Settings, conn: sqlite3.Connection, ref: str) -> str:
    return docs.read(conn, ref) or f"no document {ref!r}"


@tool("repo_info", "Health of a public GitHub repo (owner/name): stars, last push, open issues, license, archived, "
      "latest release. Use it to compare tools or check if something is maintained.", {"repo": S})  # fmt: skip
def repo_info(s: Settings, conn: sqlite3.Connection, repo: str) -> dict:
    return sources.repo_info(repo.strip().removeprefix("https://github.com/").strip("/"))


@tool("github_status", "The user's open GitHub work: their PRs (review decision, CI checks), issues assigned to "
      "them, PRs waiting for their review, PRs merged in the last week, and their own repos by last push.", {}, [])  # fmt: skip
def github_status(s: Settings, conn: sqlite3.Connection) -> dict:
    return github.status()


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
