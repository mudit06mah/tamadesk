"""Where items come from. Each source is one small function: params -> list[Item].

Only login-free, free channels: official public APIs (arXiv, Hacker News Algolia, GitHub search),
any RSS/Atom feed (blogs, news, YouTube channels, subreddits are NOT used), and agent-reach's
login-free channels: Exa semantic web search (via mcporter) and Jina Reader for page text.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape

from tamadesk.core.net import get_json, get_text


@dataclass
class Item:
    ext_id: str
    title: str
    url: str = ""
    subtitle: str = ""
    body: str = ""
    published: str = ""  # ISO date if known
    data: dict = field(default_factory=dict)


SOURCES: dict[str, Callable[..., list[Item]]] = {}


def source(name: str):
    def reg(fn):
        SOURCES[name] = fn
        return fn

    return reg


def clean(s: str, n: int = 600) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(s or ""))).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def uid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- feeds (RSS 2.0 + Atom)

ATOM = "{http://www.w3.org/2005/Atom}"


def _text(e: ET.Element, tag: str) -> str:
    el = e.find(tag)
    if el is None:
        el = e.find(ATOM + tag)
    return (el.text or "") if el is not None else ""


def parse_feed(xml: str, limit: int = 30) -> list[Item]:
    """RSS 2.0 or Atom -> Items. Shared by `rss` and `arxiv` (arXiv's API speaks Atom)."""
    root = ET.fromstring(xml)
    out = []
    for e in (root.findall(".//item") or root.findall(f"{ATOM}entry"))[:limit]:
        t = lambda tag, e=e: _text(e, tag)
        link = t("link")
        if not link and (el := e.find(f"{ATOM}link")) is not None:
            link = el.get("href", "")
        authors = [clean(a.findtext(f"{ATOM}name") or "") for a in e.findall(f"{ATOM}author")]
        title = clean(t("title"), 200)
        out.append(Item(
            ext_id=uid(t("guid") or t("id") or link or title), title=title, url=link.strip(),
            subtitle=", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "") or clean(t("author"), 80),
            body=clean(t("description") or t("summary") or t("content")),
            published=(t("pubDate") or t("published") or t("updated")).strip(),
        ))  # fmt: skip
    return out


@source("rss")
def rss(url: str, limit: int = 30) -> list[Item]:
    return parse_feed(get_text(url), limit)


@source("arxiv")
def arxiv(query: str, limit: int = 20) -> list[Item]:
    topics = [w.strip() for w in query.split(",") if w.strip()]
    q = " OR ".join(f'all:"{w}"' if " " in w else f"all:{w}" for w in topics)
    xml = get_text("https://export.arxiv.org/api/query", params={
        "search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": limit,
    }, timeout=40)  # fmt: skip
    return parse_feed(xml, limit)


# ---------------------------------------------------------------- JSON APIs


@source("hn")
def hn(query: str = "", min_points: int = 30, limit: int = 30) -> list[Item]:
    """Hacker News stories (Algolia API). No query = what's hot on the front page."""
    params = {"tags": "story", "hitsPerPage": limit, "numericFilters": f"points>{min_points}"}
    url = "https://hn.algolia.com/api/v1/search_by_date" if query else "https://hn.algolia.com/api/v1/search"
    if query:
        # comma-separated topics: any of them may match
        params |= {"query": query.replace(",", " "), "optionalWords": query.replace(",", " ")}
    else:
        params["tags"] = "front_page"
    hits = get_json(url, params=params)["hits"]
    return [Item(
        ext_id=f"hn{h['objectID']}", title=clean(h.get("title") or "", 200),
        url=h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
        subtitle=f"{h.get('points', 0)} points · {h.get('num_comments') or 0} comments",
        body=clean(h.get("story_text") or ""), published=h.get("created_at", ""),
        data={"discussion": f"https://news.ycombinator.com/item?id={h['objectID']}"},
    ) for h in hits if h.get("title")]  # fmt: skip


@source("github")
def github(query: str, days: int = 30, limit: int = 20) -> list[Item]:
    """Repos created in the last `days` days, most-starred first (unauthenticated GitHub search API).
    GitHub can't OR qualifiers ("topic:a OR topic:b"), so each alternative is searched and merged."""
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    seen: dict[int, dict] = {}
    for q in re.split(r"\s+OR\s+", query)[:4]:
        data = get_json("https://api.github.com/search/repositories", params={
            "q": f"{q} created:>{since}", "sort": "stars", "order": "desc", "per_page": limit,
        })  # fmt: skip
        seen |= {r["id"]: r for r in data.get("items", []) if r["id"] not in seen}
    repos = sorted(seen.values(), key=lambda r: -r["stargazers_count"])[:limit]
    return [Item(
        ext_id=f"gh{r['id']}", title=r["full_name"], url=r["html_url"],
        subtitle=f"★ {r['stargazers_count']} · {r.get('language') or 'n/a'}",
        body=clean(r.get("description") or ""), published=r.get("created_at", ""),
        data={"topics": r.get("topics", [])},
    ) for r in repos]  # fmt: skip


# ---------------------------------------------------------------- agent-reach (login-free channels)


def agent_reach_ready() -> bool:
    return shutil.which("mcporter") is not None


@source("exa")
def exa(query: str, limit: int = 10, objective: str = "") -> list[Item]:
    """Exa semantic web search through agent-reach's mcporter config (free, no key, no login).
    Good for things without a feed: companies, people's blogs, niche news."""
    if not agent_reach_ready():
        raise RuntimeError(
            "web search needs agent-reach's mcporter, which isn't on tamadesk's PATH. Install it "
            "(pipx install agent-reach && agent-reach install), or if you have it, reinstall the service "
            "so it picks up your PATH (see README, 'Start at login')"
        )
    proc = subprocess.run(
        ["mcporter", "call", "exa.web_search_exa", f"query={query}", f"numResults:{limit}",
         f"objective={objective or 'the most relevant, recent pages'}", "--output", "json"],
        capture_output=True, text=True, timeout=90, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"exa search failed: {proc.stderr[-200:]}")
    text = "\n".join(c.get("text", "") for c in json.loads(proc.stdout).get("content", []))
    return parse_exa(text)


def parse_exa(text: str) -> list[Item]:
    out = []
    for block in re.split(r"\n---\n", text):
        title, url = (
            re.search(r"^Title:\s*(.+)$", block, re.MULTILINE),
            re.search(r"^URL:\s*(\S+)", block, re.MULTILINE),
        )
        if not title or not url:
            continue
        date = re.search(r"^Published:\s*(\S+)", block, re.MULTILINE)
        body = block.split("Highlights:", 1)[-1] if "Highlights:" in block else ""
        host = re.sub(r"^www\.", "", url[1].split("/")[2]) if url[1].count("/") >= 2 else ""
        out.append(Item(ext_id=uid(url[1]), title=clean(title[1], 200), url=url[1], subtitle=host,
                        body=clean(re.sub(r"[#*\[\]]", " ", body)),
                        published=date[1] if date and date[1] != "N/A" else ""))  # fmt: skip
    return out


@source("agent")
def agent(task: str, limit: int = 8) -> list[Item]:
    """A Claude run with the free search tools that curates items for a fuzzy need. Costs tokens on
    every refresh, so tabs should use it only when no feed or search query can express the need."""
    from tamadesk.assistant import runner
    from tamadesk.core import db
    from tamadesk.core.config import get_settings

    schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
        "type": "object", "required": ["title", "url"],
        "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "subtitle": {"type": "string"},
                       "body": {"type": "string", "description": "1-2 sentences on why it fits"}}}}}}  # fmt: skip
    s = get_settings()
    conn = db.connect(s.db_path)
    try:
        out = runner.structured(s, conn, f"Find up to {limit} fresh, specific results for this standing request, "
                                f"using the search tool. Return only items, no commentary.\nRequest: {task}",
                                schema, kind="agent_tab", budget=min(0.3, s.assistant.max_usd_per_ask))  # fmt: skip
    finally:
        conn.close()
    return [Item(ext_id=uid(i["url"]), title=clean(i["title"], 200), url=i["url"], subtitle=i.get("subtitle", ""),
                 body=clean(i.get("body", ""))) for i in out["items"][:limit]]  # fmt: skip


def read_page(url: str, limit: int = 6000) -> str:
    """Page text via Jina Reader (agent-reach's 'any web page' channel). Used for on-demand summaries."""
    return get_text(f"https://r.jina.ai/{url}", headers={"X-Return-Format": "text"}, timeout=40)[:limit]


def fetch(spec: dict) -> list[Item]:
    params = {k: v for k, v in spec.items() if k != "type"}
    return SOURCES[spec["type"]](**params)
