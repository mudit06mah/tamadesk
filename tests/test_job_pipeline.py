"""Job search that learns: narrow queries, originals only, company job boards watched once found,
closed and old postings dropped, companies screened against the user's preferences. No network."""

import json
from datetime import UTC, datetime, timedelta

from tamadesk.life import upnext
from tamadesk.modules import engine, fit, postings, screen, sources, spec
from tamadesk.modules.sources import Item


def test_only_original_postings_count():
    assert postings.kind("https://jobs.ashbyhq.com/acme/1b2c") == "ats"
    assert postings.kind("https://boards.greenhouse.io/acme/jobs/123") == "ats"
    assert postings.kind("https://acme.example/careers/product-design-intern") == "careers"
    assert (
        postings.kind("https://careers.acme.de/jobs/ux-intern") == "careers"
    )  # a company's own careers site
    # a company on its own .careers domain
    assert postings.kind("https://notify.careers/postings/1f49") == "careers"
    for board in ["https://careercenter.example.edu/jobs/design-intern/",  # a school career centre
                  "https://remoteok.com/remote-jobs/123-ux-intern",  # an aggregator
                  "https://somesite.example/job/123-ux-intern",  # a third-party job page
                  "https://jobs.somevc.example/jobs/acme/6180005004-design-intern",  # a portfolio board
                  "https://github.com/acme/site/blob/main/careers/design.md",  # not a posting at all
                  "https://www.jobs.ca/openverse/jobs/ui-ux-designer-intern"]:  # a country job board  # fmt: skip
        assert not postings.original(board), board
    assert postings.board_of("https://job-boards.greenhouse.io/acme/jobs/7") == ("greenhouse", "acme")
    assert postings.board_of("https://apply.workable.com/acme/j/AB12/") == ("workable", "acme")
    assert postings.board_of("https://acme.recruitee.com/o/designer") == ("recruitee", "acme")
    assert postings.board_of("https://acme.example/careers/x") is None


def test_queries_are_narrow_and_posting_shaped():
    f = fit.Fit(level="intern", roles=["ux design", "product designer"])
    assert postings.queries(f, f.roles, "remote") == [
        "ux design intern job posting, remote, apply on the company's careers page",
        "product designer intern job posting, remote, apply on the company's careers page",
        "a company hiring a ux design intern, remote: the open role on their careers page",
        "a company hiring a product designer intern, remote: the open role on their careers page",
    ]
    assert len(postings.queries(f, ["a", "b", "c", "d"], limit=6)) == 6


def test_closed_pages_and_old_postings():
    assert postings.page_state("<h1>Sorry, this job is no longer accepting applications</h1>") == "closed"
    assert postings.page_state("<h1>Product Design Intern</h1><button>Apply</button>") == "open"
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    assert postings.too_old(old, 60) and not postings.too_old(old, None) and not postings.too_old("", 60)


def test_an_empty_search_answer_is_retried(monkeypatch):
    answers = [[], [Item(ext_id="1", title="Design Intern", url="https://jobs.lever.co/acme/1")]]
    monkeypatch.setattr(sources, "_exa", lambda q, n, o: answers.pop(0))
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    assert [i.title for i in sources._exa_retry("q", 10, "o")] == ["Design Intern"]


def test_job_search_keeps_originals_and_learns_their_boards(monkeypatch):
    found = [Item(ext_id="1", title="UX Intern", url="https://jobs.ashbyhq.com/acme/1"),
             Item(ext_id="2", title="UX Intern", url="https://remoteok.com/remote-jobs/2-ux-intern"),
             Item(ext_id="3", title="UX Intern", url="https://beta.example/careers/ux-intern")]  # fmt: skip
    monkeypatch.setattr(sources, "_exa_retry", lambda q, n, o: found)
    got = sources.job_search("ux design", level="intern")
    assert [i.url for i in got] == [
        "https://jobs.ashbyhq.com/acme/1",
        "https://beta.example/careers/ux-intern",
    ]
    assert got[0].data["board"] == "ashby:acme" and got[1].data["apply_url"] == got[1].url


def test_a_refresh_learns_checks_and_screens(conn, monkeypatch):
    now = datetime.now(UTC).isoformat()
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    searched = [
        Item(ext_id="a", title="UX Design Intern", url="https://jobs.ashbyhq.com/acme/a", published=now,
             data={"board": "ashby:acme", "company": "acme"}),
        Item(ext_id="b", title="UX Design Intern", url="https://closed.example/careers/b", published=now),
        Item(ext_id="c", title="UX Design Intern", url="https://stale.example/careers/c", published=old),
        Item(ext_id="d", title="UX Design Intern", url="https://coinz.example/careers/d", body="a crypto exchange"),
        Item(ext_id="e", title="UX Design Intern", url="https://grind.example/careers/e", body="we move fast"),
    ]  # fmt: skip
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: searched)
    board = {"jobs": [{"title": "Product Design Intern", "applyUrl": "https://jobs.ashbyhq.com/acme/z", "location": "Remote",
                       "publishedAt": now}]}  # fmt: skip
    monkeypatch.setattr(sources, "get_json", lambda url, **kw: board if "ashbyhq.com/posting-api/job-board/acme" in url
                        else (_ for _ in ()).throw(OSError()))  # fmt: skip
    asked = []

    class Brain:
        def ask(self, prompt, schema, **kw):
            asked.append(prompt)
            return {"verdicts": [{"company": "grind.example", "ok": False, "why": "hustle culture"},
                                 {"company": "acme", "ok": True, "why": "small design team"}]}  # fmt: skip

    m = spec.Module(id="jobs", name="Jobs", sources=[{"type": "fake"}], watch_boards=True, verify=True,
                    max_age_days=60, screen=True, fit=fit.Fit(level="intern", roles=["design"]))  # fmt: skip
    about = {"avoid": "crypto, on-site only", "wants": "calm, design-led teams"}

    def check(url):
        return "closed" if "closed." in url else "open"

    r = engine.run(conn, m, brain=Brain(), about=about, check=check)
    assert r["left_out"] == {"too old": 1, "closed": 1, "against your preferences": 2}
    assert conn.execute("SELECT board FROM boards").fetchall()[0][0] == "ashby:acme"
    titles = {row[0] for row in conn.execute("SELECT url FROM items WHERE status = 'new'")}
    assert titles == {"https://jobs.ashbyhq.com/acme/a"}
    assert "acme" in asked[0] and "crypto" in asked[0]  # the crypto one never needed the model
    r2 = engine.run(conn, m, brain=Brain(), about=about, check=check)  # now the learned board is read too
    assert r2["added"] == 1 and len(asked) == 1  # verdicts are cached per company
    item = conn.execute("SELECT data FROM items WHERE url = 'https://jobs.ashbyhq.com/acme/z'").fetchone()
    assert json.loads(item[0])["live"] == "open"  # a board's own list is live: no page check needed


def test_screening_without_preferences_spends_nothing(conn):
    assert screen.screen(conn, {}, [{"company": "acme", "text": "anything"}], brain=None) == {}
    assert screen.rule("Onsite only, 5 days a week", ["on-site only"]) == "on-site only"


def test_kept_postings_that_close_stop_asking(conn):
    data = json.dumps({"apply_url": "https://jobs.lever.co/acme/1"})
    conn.execute("INSERT INTO items (module, ext_id, source, title, data, status, decided_at) VALUES "
                 "('jobs', 'k', 'x', 'Design Intern', ?, 'saved', datetime('now', '-5 days'))", (data,))  # fmt: skip
    assert [r["kind"] for r in upnext.up_next(conn)] == ["kept"]
    assert engine.recheck_kept(conn, check=lambda url: "closed") == 1
    assert upnext.up_next(conn) == []
    assert engine.recheck_kept(conn, check=lambda url: "closed") == 0  # not checked again


def test_a_blank_optional_field_keeps_its_source():
    m = spec.from_template("jobs", {"role": "ux design", "level": "intern"})
    types = [x.type for x in m.sources]
    assert "job_search" in types and "company_jobs" not in types  # no companies typed: that one can't run
