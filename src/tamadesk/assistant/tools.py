"""The tools the assistant can use on the user's desk (served over MCP by `assistant.mcp`).

Each tool is a plain function plus a JSON schema. They reuse the same code as the HTTP API, so
anything Bolt does is exactly what the buttons do.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime

from tamadesk.core import clock, db
from tamadesk.core.config import Settings
from tamadesk.core.net import fetch, get_json
from tamadesk.life import actions, capture, docs, github, memory
from tamadesk.modules import engine, rank, sources, spec, youtube
from tamadesk.modules import fit as fitting

FEEDS = sorted(k for k in sources.SOURCES if k != "agent")
TOOLS: dict[str, tuple[str, dict, Callable]] = {}


def tool(name: str, description: str, props: dict, required: list[str] | None = None):
    schema = {"type": "object", "properties": props, "required": required or list(props)}

    def reg(fn):
        TOOLS[name] = (description, schema, fn)
        return fn

    return reg


S = {"type": "string"}


def _local(utc_naive: datetime) -> str:
    """A naive UTC datetime as the user reads it: 'Fri 16 Oct 17:00'."""
    return clock.local(clock.sql_ts(utc_naive)).strftime("%a %d %b %H:%M")


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
      "exa {query: describe the ideal page, 'category:company …' for companies}. "
      "fit {level, roles, avoid, min} drops results that don't match (e.g. senior roles in an internship search).",
      {"source": {"enum": FEEDS}, "params": {"type": "object"}, "limit": {"type": "integer"},
       "fit": {"type": "object"}}, ["source", "params"])  # fmt: skip
def search(s: Settings, conn: sqlite3.Connection, source: str, params: dict, limit: int = 8,
           fit: dict | None = None) -> list[dict] | str:  # fmt: skip
    f = fitting.Fit(**fit) if fit else None
    params = dict(params) | ({"limit": limit * (3 if f else 1)} if source != "rss" else {})
    found = sources.fetch({"type": source, **params})
    kept = [it for it in found if fitting.keeps(f, it.title, it.body)[0]][:limit]
    if f and not kept:
        return (
            f"{len(found)} results, none fit (level {f.level or 'any'}, roles {', '.join(f.roles) or 'any'})"
        )
    return [_short(it) for it in kept]


@tool("read_page", "Read a web page as plain text (Jina Reader); for a YouTube link, the video's transcript. "
      "Use sparingly: pages are long.", {"url": S})  # fmt: skip
def read_page(s: Settings, conn: sqlite3.Connection, url: str) -> str:
    return sources.transcript(url, 8000) or sources.read_page(url, 6000)


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
      "notify: true pings the desktop when something new arrives (status pages, launches, releases). "
      "workflows: up to 4 one-click {label, prompt} for what the user would do next with kept items "
      "(e.g. papers: 'Write a blog post'; jobs: 'Draft applications'), always add 1-3 that fit. "
      "fit: for jobs (and anything with a level), {level: intern|junior|mid|senior, roles: [title words], "
      "avoid: [words never wanted in a title], min: 0-1 (default 0.6)}: items below it are dropped, free. "
      "Put the level in the search queries too ('ux design internship'). "
      "News about a person, company or place: 'news' sources {query: 'Starlink India', market: 'en-in' optional}, "
      "one per angle, plus match: [names the stories must mention]; off-topic items are dropped free. "
      "layout 'steps' (with a 'roadmap' source {subject, topics: in learning order, one per line}, every '30d', "
      "actions [done, skip, open, summarize]) makes a learning path: the best few videos per topic, ticked off in order.",
      {"name": S, "icon": S, "every": S, "fit": {"type": "object"}, "layout": {"enum": ["feed", "steps"]},
       "match": {"type": "array", "items": S},
       "sources": {"type": "array", "items": {"type": "object"}}, "interests": {"type": "array", "items": S},
       "actions": {"type": "array", "items": S}, "notify": {"type": "boolean"},
       "workflows": {"type": "array", "items": {"type": "object", "properties": {"label": S, "prompt": S}}}},
      ["name", "sources"])  # fmt: skip
def create_tab(s: Settings, conn: sqlite3.Connection, **kw) -> dict | str:
    m = spec.Module(**{"id": spec.slug(kw["name"])} | kw)  # validated here, so errors come back to the model
    if problems := _broken(m):
        return "not created, these sources don't work, replace them and try again:\n" + "\n".join(problems)
    # the desk's own API installs it, so the running scheduler picks it up and fills it now
    return get_json(f"{_api(s)}/modules/spec", body=m.model_dump(), timeout=15)


@tool("update_tab", "Change an existing tab (by id or name): e.g. replace a broken source, change the schedule, "
      "interests, match or notify. Pass only the fields to change; 'sources' replaces the whole list. "
      "Adding a topic ('also Starlink in India'): add a source for it AND add its name to match.",
      {"tab": S, "name": S, "icon": S, "every": S, "sources": {"type": "array", "items": {"type": "object"}},
       "interests": {"type": "array", "items": S}, "actions": {"type": "array", "items": S},
       "notify": {"type": "boolean"}, "fit": {"type": "object"}, "match": {"type": "array", "items": S}},
      ["tab"])  # fmt: skip
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
        spec_ = src.model_dump()
        if src.type == "roadmap":  # one topic is enough to know it works; the refresh does the rest
            spec_ |= {"topics": re.split(r"\n|,|;", spec_.get("topics", ""))[0], "per_topic": 1}
        try:
            got = sources.fetch(spec_)
            if not got:
                problems.append(f"{src.model_dump()} returned nothing")
            elif (words := m.match or m.interests) and src.type != "roadmap":
                # results aren't enough: they have to be about the tab (a loose search fills it with noise)
                on = [i for i in got if engine.on_topic(words, f"{i.title} {i.body}")]
                if len(on) < max(1, len(got) * 0.4):
                    problems.append(f"{src.model_dump()} is mostly off topic: {len(on)} of {len(got)} mention "
                                    f"{', '.join(words[:6])}. Narrow it (every word of a query must match) or use 'news'")  # fmt: skip
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
    youtube.fill(conn, m.id)  # videos get their channel, length, picture and description
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


@tool("remember", "Save something the user told you about themselves, so tabs, searches and emails use it "
      "and you never ask twice. key: level (internship|junior|mid|senior), roles (comma separated), "
      "location (e.g. 'remote, India'), avoid (deal-breakers: 'unpaid, crypto, on-site only'), wants (what "
      "makes a place good for them), or note (anything else worth knowing long-term: a skill, a preference, "
      "a fact; it goes on their profile card). Job tabs skip companies that clash with avoid/wants.",
      {"key": {"enum": ["level", "roles", "location", "avoid", "wants", "note"]}, "value": S})  # fmt: skip
def remember(s: Settings, conn: sqlite3.Connection, key: str, value: str) -> str:
    if key == "note":
        from tamadesk.life import profile

        profile.add_note(s, value)
        return f"noted on their profile card: {value.strip()[:200]}"
    about = db.get_profile(conn, "about", {}) | {key: value.strip()[:200]}
    db.set_profile(conn, "about", about)
    return f"remembered {key}: {value.strip()[:200]}"


@tool(
    "add_todo",
    "Add a todo. Set `due` (natural language: 'friday 5pm', 'in 3 days') whenever the user gives or implies a "
    "deadline ('before the interview', 'this week'); the companion builds pressure as it gets close.",
    {"title": S, "due": S},
    ["title"],
)
def add_todo(s: Settings, conn: sqlite3.Connection, title: str, due: str = "") -> str:
    c = capture.parse(f"todo {title} {due}".strip())
    with db.transaction(conn):
        actions.add_todo(conn, c.text, clock.sql_ts(c.due_at) if c.due_at else None)
    return "added" + (f", due {_local(c.due_at)}" if c.due_at else "")


@tool("list_todos", "The user's open todos (with due times, repeats, who they wait on), their pending reminders, "
      "and what they finished today. Ids here are for complete_todo, drop_todo, set_deadline, cancel_reminder.",
      {}, [])  # fmt: skip
def list_todos(s: Settings, conn: sqlite3.Connection) -> dict:
    from tamadesk.api.routes import day_start_utc

    open_ = conn.execute(
        "SELECT id, title, due_at, repeat, kind, who, tags FROM todos WHERE status = 'open' "
        "ORDER BY due_at IS NULL, due_at, id"
    )
    done = conn.execute(
        "SELECT id, title FROM todos WHERE status = 'done' AND done_at >= ?", (day_start_utc(),)
    )
    return {
        "open": [dict(r) | {"due": _local_ts(r["due_at"])} for r in open_],
        "done_today": [dict(r) for r in done],
        "reminders": [
            {"id": r["id"], "text": r["text"], "due": _local_ts(r["due_at"]), "repeat": r["repeat"]}
            for r in conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND cal_key IS NULL ORDER BY due_at"
            )
        ],
    }


@tool("complete_todo", "Mark one of the user's todos done (by id from list_todos), when they say they finished it.",
      {"id": {"type": "integer"}})  # fmt: skip
def complete_todo(s: Settings, conn: sqlite3.Connection, id: int) -> str:
    return "done" if actions.complete_todo(conn, id) else f"no open todo #{id}"


@tool("desk", "Run one of the desk's instant shortcuts, exactly as if the user typed it: 'todo X every weekday "
      "10am #tag', 'done X', 'move X to fri', 'waiting on X from Y by thu', 'meeting X at 3pm for 30 min', "
      "'focus 25 #tag', 'remind me to X every sunday 6pm'. Use it for repeating todos, waiting-on, meetings "
      "and focus sessions.", {"text": S})  # fmt: skip
def desk(s: Settings, conn: sqlite3.Connection, text: str) -> str:
    r = actions.capture_text(conn, text)
    return r["message"] or f"{r['kind']}: {r['text']}"


@tool("review", "Look back, for free: 'standup' (yesterday, today, blockers), 'week' (the week card: XP, "
      "on-time finishes, focus hours per #tag, the title earned) or 'brag' (everything done since `since`, "
      "YYYY-MM-DD, grouped by month and tag; for reviews and resumes).",
      {"kind": {"enum": ["standup", "week", "brag"]}, "since": S}, ["kind"])  # fmt: skip
def review(s: Settings, conn: sqlite3.Connection, kind: str, since: str = "") -> str:
    from datetime import date, timedelta

    from tamadesk.life import review as reviews
    from tamadesk.life.today import local_today

    if kind == "standup":
        return reviews.standup(conn)["markdown"]
    if kind == "week":
        return reviews.week(conn)["markdown"]
    try:
        start = date.fromisoformat(since) if since else local_today() - timedelta(days=90)
    except ValueError:
        return "since must be YYYY-MM-DD"
    return reviews.brag(conn, start)["markdown"]


@tool("drop_todo", "Remove one of the user's todos (by id from list_todos) when they want it gone. For a "
      "repeating one, stop_repeating=true removes the whole habit (the default); false only skips this time. "
      "Never mark a todo done just to make it disappear: done means they did it.",
      {"id": {"type": "integer"}, "stop_repeating": {"type": "boolean"}}, ["id"])  # fmt: skip
def drop_todo(s: Settings, conn: sqlite3.Connection, id: int, stop_repeating: bool = True) -> str:
    row = conn.execute("SELECT title, repeat FROM todos WHERE id = ? AND status = 'open'", (id,)).fetchone()
    if row is None or not actions.drop_todo(conn, id, stop=stop_repeating):
        return f"no open todo #{id}"
    if row["repeat"]:
        return f"removed '{row['title']}'" + (
            " and stopped it repeating" if stop_repeating else " (skipped this time)"
        )
    return f"removed '{row['title']}'"


@tool("cancel_reminder", "Cancel one of the user's reminders (by id from list_todos) so it won't ring. A "
      "repeating one stops for good.", {"id": {"type": "integer"}})  # fmt: skip
def cancel_reminder(s: Settings, conn: sqlite3.Connection, id: int) -> str:
    return "cancelled" if actions.cancel_reminder(conn, id) else f"no pending reminder #{id}"


@tool("set_deadline", "Give one of the user's open todos a deadline, or move it (by id from list_todos). "
      "`when` in plain words ('fri 5pm', 'in 2 days'); empty clears it.", {"id": {"type": "integer"}, "when": S})  # fmt: skip
def set_deadline(s: Settings, conn: sqlite3.Connection, id: int, when: str) -> str:
    try:
        due = actions.set_due(conn, id, when)
    except ValueError as e:
        return str(e)
    return f"deadline {_local_ts(due)} (the user's local time)" if due else "deadline cleared"


@tool("set_reminder", "Ring the user at a time ('in 20 min', 'tomorrow 9am').", {"text": S, "when": S})
def set_reminder(s: Settings, conn: sqlite3.Connection, text: str, when: str) -> str:
    c = capture.parse(f"remind me to {text} {when}")
    if c.kind != "reminder":
        return f"couldn't understand the time {when!r}"
    with db.transaction(conn):
        actions.add_reminder(conn, c.text, clock.sql_ts(c.due_at))
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


@tool("write_note", "Save a piece of writing for the user to the Notes page (markdown): blog drafts, study "
      "notes, digests, comparisons. Same title replaces the earlier version.", {"title": S, "markdown": S})  # fmt: skip
def write_note(s: Settings, conn: sqlite3.Connection, title: str, markdown: str) -> str:
    from tamadesk.life.writer import clean

    nid = docs.save_note(conn, title, clean(markdown))
    return f"saved to Notes as '{title}' (#{nid})"


@tool("my_day", "The user's day as one ordered list: meetings (with join links), reminders, todos due, what's "
      "waiting on them (replies, follow-ups, drafts, with the things only they can do) and what they already did. "
      "Use for 'what's my day?', 'what's next?', 'am I free at 3?'. `day` is YYYY-MM-DD, empty for today.",
      {"day": S}, [])  # fmt: skip
def my_day(s: Settings, conn: sqlite3.Connection, day: str = "") -> dict | str:
    from datetime import date

    from tamadesk.life import today

    try:
        d = date.fromisoformat(day) if day else None
    except ValueError:
        return "day must be YYYY-MM-DD"
    return today.brief(conn, d, recap_at=s.day.bed_at)


@tool("pipeline", "Where the user's jobs and leads stand: what's been emailed or applied to, replies, interviews, "
      "and anything waiting on them (Up next). Use for 'what's happening with my applications/outreach?'.", {}, [])  # fmt: skip
def pipeline_status(s: Settings, conn: sqlite3.Connection) -> dict:
    from tamadesk.life import upnext

    rows = conn.execute("SELECT id, module, title, url, stage, stage_at FROM items WHERE stage IS NOT NULL "
                        "ORDER BY stage_at DESC LIMIT 40").fetchall()  # fmt: skip
    mail_in = conn.execute("SELECT id, kind, from_name, from_addr, subject, snippet, draft_id, item_id, status "
                           "FROM inbox ORDER BY id DESC LIMIT 15").fetchall()  # fmt: skip
    return {"items": [dict(r) for r in rows], "inbox": [dict(r) | {"snippet": (r["snippet"] or "")[:300]} for r in mail_in],
            "up_next": upnext.up_next(conn)}  # fmt: skip


@tool("set_stage", "Record where a job/lead stands when the user tells you (e.g. 'I applied to Linear'): "
      "emailed|applied|replied|interview|rejected|done.", {"item_id": {"type": "integer"}, "stage": S})  # fmt: skip
def set_stage(s: Settings, conn: sqlite3.Connection, item_id: int, stage: str) -> str:
    from tamadesk.life import pipeline

    with db.transaction(conn):
        return (
            "updated"
            if pipeline.set_stage(conn, item_id, stage, why="you told me", manual=True)
            else "no change"
        )


@tool("github_status", "The user's open GitHub work: their PRs (review decision, CI checks), issues assigned to "
      "them, PRs waiting for their review, PRs merged in the last week, and their own repos by last push.", {}, [])  # fmt: skip
def github_status(s: Settings, conn: sqlite3.Connection) -> dict:
    return github.status()


@tool("draft_email", "Save an email draft to the user's Mail tab for them to review and send. Never says it was "
      "sent. to_email must be published on a page you saw (email_source = that URL); if you guessed it, set "
      "email_sure false. item_id links a lead from a tab.",
      {"subject": S, "body": S, "to_name": S, "to_email": S, "email_source": S, "email_sure": {"type": "boolean"},
       "item_id": {"type": "integer"}, "reply_to": {"type": "integer", "description": "the sent draft id this "
       "answers or follows up on: keeps the thread, recipient and item"}}, ["subject", "body"])  # fmt: skip
def draft_email(s: Settings, conn: sqlite3.Connection, subject: str, body: str, **kw) -> str:
    from tamadesk.life.writer import clean

    parent = kw.pop("reply_to", None)
    kind = "first"
    if parent and conn.execute("SELECT 1 FROM drafts WHERE id = ?", (parent,)).fetchone():
        kind = (
            "reply"
            if conn.execute("SELECT 1 FROM inbox WHERE draft_id = ?", (parent,)).fetchone()
            else "followup"
        )
    with db.transaction(conn):
        rid = actions.add_draft(conn, ask="bolt", subject=clean(subject), body=clean(body), parent_id=parent,
                                kind=kind, **kw)  # fmt: skip
    return f"draft #{rid} saved to Mail"


def call(s: Settings, name: str, args: dict) -> str:
    conn = db.connect(s.db_path)
    try:
        out = TOOLS[name][2](s, conn, **args)
    finally:
        conn.close()
    return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
