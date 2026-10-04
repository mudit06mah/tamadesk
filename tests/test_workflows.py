"""Jobs straight from companies, tab workflows, and notes."""

import pytest
from pydantic import ValidationError

from tamadesk.assistant import tools
from tamadesk.core.config import get_settings
from tamadesk.modules import sources, spec
from tamadesk.modules.sources import Item

HIT = {
    "objectID": "42",
    "created_at": "2026-10-01T00:00:00Z",
    "comment_text": 'Acme | Product Designer | REMOTE (EU) | <a href="https:&#x2F;&#x2F;acme.dev&#x2F;careers&#x2F;designer">'
    "acme.dev/careers</a><p>We build tools. Email jobs@acme.dev with your portfolio.",
}


def test_parse_hiring_finds_apply_link_and_published_email():
    i = sources.parse_hiring(HIT)
    assert i.title.startswith("Acme | Product Designer")
    assert i.url == i.data["apply_url"] == "https://acme.dev/careers/designer"
    assert i.data["email"] == "jobs@acme.dev" and i.data["email_source"].endswith("id=42")


def test_hn_jobs_matches_the_role_line_and_skips_seekers(monkeypatch):
    seeker = {
        "objectID": "7",
        "comment_text": "sam | Location: Berlin | Remote: yes | Willing to relocate | designer",
    }
    unrelated = {"objectID": "8", "comment_text": "Beta | Embedded Engineer | REMOTE | we love good ux"}

    def fake(url, params, **kw):
        if "search_by_date" in url:
            return {"hits": [{"objectID": "1", "title": "Ask HN: Who is hiring? (October 2026)"}]}
        return {"hits": [HIT, seeker, unrelated]}

    monkeypatch.setattr(sources, "get_json", fake)
    assert [i.title.split(" |")[0] for i in sources.hn_jobs("product designer, ux", remote=True)] == ["Acme"]


def test_company_jobs_direct_apply_links(monkeypatch):
    board = {"jobs": [{"title": "Design Engineer", "jobUrl": "https://jobs.ashbyhq.com/linear/1", "applyUrl": "https://jobs.ashbyhq.com/linear/1/application", "location": "Remote"},
                      {"title": "Account Executive", "jobUrl": "u2", "location": "SF"}]}  # fmt: skip
    monkeypatch.setattr(
        sources, "get_json", lambda url, **kw: board if "ashbyhq" in url else (_ for _ in ()).throw(OSError())
    )
    (j,) = sources.company_jobs("linear", "design")
    assert j.url.endswith("/application") and j.title == "Design Engineer at linear"


def test_exa_never_returns_login_walls(monkeypatch):
    monkeypatch.setattr(sources, "_exa", lambda q, n, o: [
        Item(ext_id="1", title="a", url="https://www.linkedin.com/jobs/1"), Item(ext_id="2", title="b", url="https://acme.dev/jobs"),
        Item(ext_id="3", title="c", url="https://remotive.com/x")])  # fmt: skip
    (i,) = sources.exa("q", exclude="remotive.com")
    assert i.url == "https://acme.dev/jobs" and i.data["apply_url"] == i.url  # a careers page gets "apply"


def test_workflows_are_validated():
    m = spec.Module(id="p", name="P", sources=[{"type": "rss", "url": "u"}],
                    workflows=[{"label": "Write a blog post", "prompt": "write it up"}])  # fmt: skip
    assert m.workflows[0].label == "Write a blog post"
    with pytest.raises(ValidationError):
        spec.Module(
            id="p", name="P", sources=[{"type": "rss", "url": "u"}], workflows=[{"label": "", "prompt": "x"}]
        )


def test_notes_from_the_assistant(client):
    s = get_settings()
    assert "saved to Notes" in tools.call(
        s, "write_note", {"title": "GNN papers", "markdown": "# Draft — v1 🎉"}
    )
    tools.call(s, "write_note", {"title": "GNN papers", "markdown": "# Draft v2"})  # same title = new version
    (n,) = client.get("/api/notes").json()
    assert n["text"] == "# Draft v2"
    client.put(f"/api/notes/{n['id']}", json={"name": "GNN post", "text": "edited"})
    assert client.get("/api/notes").json()[0]["name"] == "GNN post"
    assert client.get("/api/docs").json() == []  # notes don't clutter the documents list


def test_changing_sources_refetches_unseen_but_keeps_kept(client, monkeypatch):
    from tamadesk.api.jobs import run_module

    monkeypatch.setitem(
        sources.SOURCES,
        "fake",
        lambda **kw: [Item(ext_id="a", title="old A"), Item(ext_id="b", title="old B")],
    )
    spec.save(get_settings(), spec.Module(id="j", name="J", sources=[{"type": "fake"}]))
    run_module("j")
    kept = client.get("/api/modules/j/items").json()["items"][0]
    client.post(f"/api/items/{kept['id']}/save", json={})
    m = spec.get(get_settings(), "j").model_dump() | {"sources": [{"type": "fake", "query": "new"}]}
    client.put("/api/modules/j/spec", json=m)
    assert client.get("/api/modules/j/items").json()["items"] == []  # unseen ones from the old setup are gone
    assert [i["title"] for i in client.get("/api/modules/j/items?status=saved").json()["items"]] == [
        kept["title"]
    ]
