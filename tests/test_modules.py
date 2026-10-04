import pytest
from pydantic import ValidationError

from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.modules import engine, rank, sources, spec
from tamadesk.modules.sources import Item

RSS = """<rss><channel><item><title>Hello &amp; welcome</title><link>https://a.dev/1</link>
<guid>g1</guid><description>&lt;p&gt;First post&lt;/p&gt;</description><pubDate>Sat, 03 Oct 2026</pubDate></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1</id>
<title>GPU tensor networks</title><link href="http://arxiv.org/abs/1"/><summary>We simulate.</summary>
<author><name>A. One</name></author><author><name>B. Two</name></author><published>2026-10-01</published></entry></feed>"""
EXA = """Title: Skinella | D2C
URL: https://www.skinella.com/about
Published: N/A
Author: N/A
Highlights:
# Skinella makes **superfood** skincare.
---
Title: Broken block without url"""


def test_parse_rss_and_atom():
    (r,) = sources.parse_feed(RSS)
    assert (r.title, r.url, r.body) == ("Hello & welcome", "https://a.dev/1", "First post")
    (a,) = sources.parse_feed(ATOM)
    assert (a.title, a.url, a.subtitle, a.published) == (
        "GPU tensor networks",
        "http://arxiv.org/abs/1",
        "A. One, B. Two",
        "2026-10-01",
    )


def test_parse_exa():
    (e,) = sources.parse_exa(EXA)
    assert (e.title, e.subtitle, e.published) == ("Skinella | D2C", "skinella.com", "")
    assert "superfood skincare" in e.body


def test_templates_all_valid_and_blank_params_drop_sources():
    for t in spec.templates():
        assert spec.from_template(t["key"], {}).sources
    m = spec.from_template("news", {"topics": "rust, wasm", "feed": ""})
    assert [s.type for s in m.sources] == ["hn"] and m.interests == ["rust", "wasm"]
    with pytest.raises(ValueError, match="unknown template"):
        spec.from_template("nope", {})


def test_schedule_strings():
    assert spec.trigger("30m") == ("interval", {"minutes": 30})
    assert spec.trigger("daily 08:05") == ("cron", {"hour": 8, "minute": 5})
    with pytest.raises(ValidationError):
        spec.Module(id="x", name="X", every="sometimes", sources=[{"type": "rss", "url": "u"}])


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    return c


def test_ranker_learns_from_saves_and_skips(conn):
    assert rank.score(conn, "m", "gpu kernels", ["gpu"])[0] > 0  # declared interest, day one
    rank.learn(conn, "m", "rust compiler internals", liked=True)
    rank.learn(conn, "m", "celebrity gossip roundup", liked=False)
    good, why = rank.score(conn, "m", "a new rust compiler", [])
    bad, _ = rank.score(conn, "m", "weekly gossip", [])
    assert good > 0 > bad and "rust" in why


def _module(**kw):
    return spec.Module(**{"id": "t", "name": "T", "sources": [{"type": "fake"}]} | kw)


def test_run_dedupes_ranks_prunes_and_survives_bad_sources(conn, monkeypatch):
    items = [Item(ext_id=str(i), title=f"item {i} gpu" if i < 3 else f"item {i}") for i in range(20)]
    monkeypatch.setitem(sources.SOURCES, "fake", lambda: items)
    monkeypatch.setitem(sources.SOURCES, "dead", lambda: 1 / 0)
    m = _module(sources=[{"type": "fake"}, {"type": "dead"}], interests=["gpu"], keep=10)
    r = engine.run(conn, m)
    assert r["added"] == 20 and r["errors"][0].startswith("dead")
    assert engine.run(conn, m)["added"] == 0  # same items again: nothing new
    kept = [
        x["title"]
        for x in conn.execute("SELECT title FROM items WHERE status = 'new' ORDER BY score DESC, id DESC")
    ]
    assert len(kept) == 10 and all("gpu" in t for t in kept[:3])  # best ones survive the prune


def test_actions_xp_and_undo(conn, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "fake", lambda: [Item(ext_id="1", title="rust compiler")])
    engine.run(conn, _module())
    iid = conn.execute("SELECT id FROM items").fetchone()[0]
    assert engine.act(conn, iid, "save") == {"status": "saved", "xp": 1}
    assert conn.execute("SELECT pos FROM terms WHERE term = 'rust'").fetchone()[0] == 1
    engine.act(conn, iid, "undo")
    row = conn.execute("SELECT pos, neg FROM terms WHERE term = 'rust'").fetchone()
    assert tuple(row) == (1, 1)  # undo cancels the lesson out
    assert conn.execute("SELECT status FROM items").fetchone()[0] == "new"


def test_api_create_list_act_delete(client, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "hn", lambda **kw: [Item(ext_id="1", title="Rust 2.0 released")])
    m = client.post("/api/modules", json={"template": "news", "params": {"topics": "rust"}}).json()
    assert m["id"] == "news"
    assert client.post("/api/modules", json={"template": "news"}).json()["id"] == "news-2"  # never overwrite
    from tamadesk.api.jobs import run_module

    run_module("news")
    tabs = {t["id"]: t for t in client.get("/api/modules").json()}
    assert tabs["news"]["new"] == 1 and tabs["news"]["run"]["added"] == 1
    item = client.get("/api/modules/news/items").json()["items"][0]
    assert item["why"] == ["rust"]
    assert client.post(f"/api/items/{item['id']}/save", json={}).json()["xp"] == 1
    assert client.post(f"/api/items/{item['id']}/todo").json()["todo_id"]
    bad = client.put("/api/modules/news", json={"yaml": "name: X\nevery: whenever\nsources: []"})
    assert bad.status_code == 422
    client.delete("/api/modules/news")
    assert "news" not in {t["id"] for t in client.get("/api/modules").json()}


def test_github_splits_or_queries(monkeypatch):
    calls = []

    def fake(url, params, **kw):
        calls.append(params["q"].split(" created:")[0])
        n = len(calls)
        return {"items": [{"id": n, "full_name": f"r/{n}", "html_url": "u", "stargazers_count": n}]}

    monkeypatch.setattr(sources, "get_json", fake)
    monkeypatch.setattr(sources, "_gh_headers", dict)
    out = sources.github("topic:game-engine OR topic:gamedev")
    assert calls == ["topic:game-engine", "topic:gamedev"] and [i.title for i in out] == ["r/2", "r/1"]


def test_assistant_tools_and_mcp_protocol(client, monkeypatch):
    from tamadesk.assistant import mcp, tools

    s = get_settings()
    listing = mcp.handle(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in listing["result"]["tools"]}
    assert {"search", "create_tab", "add_to_tab", "draft_email", "set_reminder"} <= names
    assert mcp.handle(s, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    r = mcp.handle(s, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "set_reminder", "arguments": {"text": "stretch", "when": "in 20 minutes"}}})  # fmt: skip
    assert "reminder set" in r["result"]["content"][0]["text"]
    bad = mcp.handle(s, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "add_to_tab",
                         "arguments": {"tab": "nope", "items": []}}})  # fmt: skip
    assert "no tab" in bad["result"]["content"][0]["text"]
    assert "draft #" in tools.call(
        s, "draft_email", {"subject": "Hey — you", "body": "hi", "email_sure": False}
    )
    assert client.get("/api/mail").json()["items"][0]["subject"] == "Hey, you"  # dashes cleaned


def test_reach_servers_only_allowed_ones(tmp_path, monkeypatch):
    import json

    from tamadesk.assistant import runner

    (tmp_path / ".mcporter").mkdir()
    (tmp_path / ".mcporter" / "mcporter.json").write_text(json.dumps({"mcpServers": {
        "exa": {"baseUrl": "https://mcp.exa.ai/mcp"}, "twitter": {"baseUrl": "https://x/mcp"}}}))  # fmt: skip
    monkeypatch.setattr(runner.Path, "home", lambda: tmp_path)
    assert runner.reach_servers(get_settings()) == {"exa": {"type": "http", "url": "https://mcp.exa.ai/mcp"}}


def test_sources_are_normalized_and_checked():
    m = spec.Module(id="x", name="X", sources=[{"type": "exa", "params": {"query": "q", "limit": 5}}])
    assert m.sources[0].model_dump() == {"type": "exa", "query": "q", "limit": 5}
    with pytest.raises(ValidationError, match="doesn't take"):
        spec.Module(id="x", name="X", sources=[{"type": "rss", "feed": "u"}])
    with pytest.raises(ValidationError, match="unknown source type"):
        spec.Module(id="x", name="X", sources=[{"type": "twitter"}])


def test_create_tab_refuses_dead_sources(client, monkeypatch):
    from tamadesk.assistant import tools

    def dead(**kw):
        raise RuntimeError("HTTP Error 401: Forbidden")

    monkeypatch.setitem(sources.SOURCES, "rss", dead)
    out = tools.call(
        get_settings(), "create_tab", {"name": "News", "sources": [{"type": "rss", "url": "https://x/feed"}]}
    )
    assert "not created" in out and "401" in out
    assert client.get("/api/modules").json() == []
