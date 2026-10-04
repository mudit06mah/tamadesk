"""The additions from the persona study: releases, issues, notify, todo tools, repo info, safety."""

import pytest
from pydantic import ValidationError

from tamadesk.assistant import runner, tools
from tamadesk.core.config import get_settings
from tamadesk.modules import sources, spec

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:r1</id><title>v1.2.0</title>
<link href="https://github.com/a/zed/releases/tag/v1.2.0"/><updated>2026-10-02T00:00:00Z</updated></entry></feed>"""


def test_every_tool_the_prompt_mentions_exists(client):
    conn_s = get_settings()
    from tamadesk.core import db

    prompt = runner.system_prompt(conn_s, db.connect(conn_s.db_path))
    for name in ("search", "create_tab", "add_to_tab", "draft_email", "recall", "day_notes"):
        assert name in prompt and name in tools.TOOLS, name  # the recall bug: promised but never registered


def test_releases_for_many_repos(monkeypatch):
    monkeypatch.setattr(
        sources, "get_text", lambda url, **kw: ATOM if "zed" in url else (_ for _ in ()).throw(OSError())
    )
    out = sources.releases("a/zed, b/nothing-here")
    assert [(i.title, i.subtitle) for i in out] == [
        ("zed v1.2.0", "a/zed")
    ]  # a repo without releases is skipped


def test_github_issues(monkeypatch):
    item = {"id": 1, "title": "Docs typo", "html_url": "u", "number": 7, "repository_url": "https://api.github.com/repos/o/r",
            "labels": [{"name": "good first issue"}], "body": "fix it", "updated_at": "2026-10-01"}  # fmt: skip
    monkeypatch.setattr(sources, "_gh_headers", dict)
    monkeypatch.setattr(sources, "get_json", lambda url, params, **kw: {"items": [item]})
    (i,) = sources.github_issues('label:"good first issue"')
    assert i.subtitle == "o/r#7 · good first issue" and i.ext_id == "ghi1"


def test_agent_tabs_are_read_only_and_not_too_frequent():
    with pytest.raises(ValidationError, match="6h"):
        spec.Module(id="x", name="X", every="30m", sources=[{"type": "agent", "task": "t"}])
    assert spec.Module(id="x", name="X", every="daily 08:00", sources=[{"type": "agent", "task": "t"}])
    cmd = runner.command(
        get_settings(), prompt="p", system="s", budget=0.1, stream=False, allowed=runner.READ_ONLY
    )
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "create_tab" not in allowed and "delete_tab" not in allowed and "mcp__tamadesk__search" in allowed


def test_todo_tools_share_the_ui_path(client):
    tid = client.post("/api/capture", json={"text": "todo ship the release"}).json()["id"]
    s = get_settings()
    assert "ship the release" in tools.call(s, "list_todos", {})
    assert tools.call(s, "complete_todo", {"id": tid}) == "done"
    assert tools.call(s, "complete_todo", {"id": tid}).startswith("no open todo")
    assert client.get("/api/state").json()["progress"]["xp"] == 10  # same XP as the checkbox


def test_reminder_reply_is_local_time(client):
    out = tools.call(get_settings(), "set_reminder", {"text": "stretch", "when": "in 20 minutes"})
    assert "UTC" not in out and "local time" in out


def test_notify_when_a_tab_gets_something_new(client, monkeypatch):
    from tamadesk.api import jobs
    from tamadesk.modules.sources import Item

    seen = []
    monkeypatch.setattr(jobs, "notify", lambda title, body: seen.append((title, body)))
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: [Item(ext_id="1", title="GitHub is down")])
    spec.save(
        get_settings(), spec.Module(id="status", name="Status", notify=True, sources=[{"type": "fake"}])
    )
    jobs.run_module("status")
    jobs.run_module("status")  # nothing new the second time: no ping
    assert seen == [("Status", "1 new")]


def test_same_link_is_one_item(client, monkeypatch):
    from tamadesk.api.jobs import run_module
    from tamadesk.modules.sources import Item

    monkeypatch.setitem(
        sources.SOURCES, "fake", lambda **kw: [Item(ext_id="gh9", title="repo", url="https://github.com/o/r")]
    )
    spec.save(get_settings(), spec.Module(id="radar", name="Radar", sources=[{"type": "fake"}]))
    tools.call(
        get_settings(),
        "add_to_tab",
        {"tab": "Radar", "items": [{"title": "repo", "url": "https://github.com/o/r"}]},
    )
    run_module("radar")  # the scheduled fetch finds the same repo under a different id
    assert len(client.get("/api/modules/radar/items").json()["items"]) == 1
