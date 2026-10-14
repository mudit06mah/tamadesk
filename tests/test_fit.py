"""Fit: a search for internships never fills up with senior roles. Zero tokens, explainable."""

import json

from tamadesk.assistant import tools
from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.modules import engine, fit, sources, spec
from tamadesk.modules.sources import Item

POSTINGS = [
    "Senior Product Designer (Remote, Europe)",
    "Staff Product Designer, FinTech",
    "Lead Product Designer - Remote - US",
    "UX Design Intern, Summer 2027",
    "Product Design Internship",
    "Associate Product Designer",
    "Software Engineering Intern",
    "Mobile Product Designer",
]


def test_an_internship_search_keeps_internships_only():
    f = fit.Fit(level="internship", roles="ux design, product designer")
    kept = [t for t in POSTINGS if fit.keeps(f, t)[0]]
    assert kept == [
        "UX Design Intern, Summer 2027",
        "Product Design Internship",
        "Associate Product Designer",
    ]
    assert fit.score(f, "Senior Product Designer")[1] == ["senior role"]  # it says why
    assert fit.keeps(None, "anything") == (True, None, [])  # tabs without fit are untouched


def test_levels_and_roles_come_from_the_users_own_words():
    assert fit.level_from_text("an internship in UI/UX design") == "intern"
    assert fit.level_from_text("my first job as a backend dev") == "junior"
    assert fit.level_from_text("not now") is None
    assert fit.roles_from_text("an internship in UI/UX design, or product design") == [
        "ux design",
        "product design",
    ]
    assert fit.profile({"looking_for": "a senior role in data science", "roles": "ml engineer"}) == {
        "level": "senior", "roles": "ml engineer", "location": ""}  # fmt: skip


def test_a_tab_drops_what_doesnt_fit_and_never_fetches_it_again(conn, monkeypatch):
    items = [Item(ext_id=f"j{i}", title=t, url=f"https://jobs.example/{i}") for i, t in enumerate(POSTINGS)]
    monkeypatch.setitem(sources.SOURCES, "hn_jobs", lambda **kw: items)
    m = spec.from_template("jobs", {}, about={"looking_for": "an internship in UX design, product design"})
    assert (m.fit.level, m.fit.roles) == ("intern", ["ux design", "product design"])
    search = next(s for s in m.sources if s.type == "job_search").model_dump()
    assert (search["level"], search["roles"]) == ("intern", "ux design, product design")
    assert m.verify and m.watch_boards and m.screen and m.max_age_days == 60
    # this test is about fit only: no network checks, no screening
    m = m.model_copy(update={"sources": [spec.Source(type="hn_jobs", query="design")], "verify": False,
                             "screen": False, "watch_boards": False})  # fmt: skip

    r = engine.run(conn, m)
    assert (r["added"], r["dropped"], r["left_out"]) == (3, 5, {"poor fit": 5})
    rows = conn.execute("SELECT title, data FROM items WHERE status = 'new' ORDER BY score DESC").fetchall()
    assert rows[0]["title"] in ("UX Design Intern, Summer 2027", "Product Design Internship")
    top = json.loads(rows[0]["data"])["fit"]
    assert top["score"] == 1.0 and top["why"][0] == "internship"
    again = engine.run(conn, m)
    assert (again["added"], again["dropped"], again["errors"]) == (0, 0, [])  # gone rows aren't refetched
    assert conn.execute("SELECT dropped FROM module_runs").fetchone()[0] == 0


def test_tightening_fit_drops_unseen_items_but_never_kept_ones(conn, monkeypatch):
    items = [Item(ext_id=f"j{i}", title=t, url=f"https://jobs.example/{i}") for i, t in enumerate(POSTINGS)]
    monkeypatch.setitem(sources.SOURCES, "hn_jobs", lambda **kw: items)
    m = spec.Module(id="jobs", name="Jobs", sources=[spec.Source(type="hn_jobs", query="design")])
    engine.run(conn, m)
    senior = conn.execute("SELECT id FROM items WHERE title LIKE 'Senior%'").fetchone()[0]
    engine.act(conn, senior, "save")
    engine.rescore(conn, m.model_copy(update={"fit": fit.Fit(level="intern", roles=["design"])}))
    left = {r[0] for r in conn.execute("SELECT title FROM items WHERE status IN ('new', 'saved')")}
    assert left == {"Senior Product Designer (Remote, Europe)", "UX Design Intern, Summer 2027",
                    "Product Design Internship", "Associate Product Designer"}  # fmt: skip


def test_bolts_one_off_search_can_filter_by_fit(conn, monkeypatch):
    items = [Item(ext_id=f"j{i}", title=t, url=f"https://jobs.example/{i}") for i, t in enumerate(POSTINGS)]
    monkeypatch.setitem(sources.SOURCES, "hn_jobs", lambda **kw: items)
    got = tools.search(
        get_settings(), conn, "hn_jobs", {"query": "design"}, fit={"level": "intern", "roles": ["design"]}
    )
    assert [g["title"] for g in got] == ["UX Design Intern, Summer 2027", "Product Design Internship",
                                         "Associate Product Designer"]  # fmt: skip
    none = tools.search(
        get_settings(), conn, "hn_jobs", {"query": "x"}, fit={"level": "senior", "roles": ["chef"]}
    )
    assert none.startswith("8 results, none fit")
    tools.remember(get_settings(), conn, "level", "internship")
    assert db.get_profile(conn, "about")["level"] == "internship"
