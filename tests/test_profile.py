"""The profile card: a resume becomes one short, editable page that every ask reads. The resume and
the person here are made up (example.com)."""

import base64

import pytest

from tamadesk.api import jobs
from tamadesk.assistant import runner, tools
from tamadesk.brain import BrainError
from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import profile

RESUME = """Robin Example | robin@example.com | robin.example/work | github.com/robin-example
Final-year interaction design student. Looking for a product design internship, remote or in Lisbon.
Design intern, Northwind (2025): redesigned onboarding, sign-up completion up 18%.
Projects: Shelf, a library app for small reading groups. Skills: Figma, prototyping, user research.
"""
CARD = {
    "headline": "Final-year interaction design student",
    "level": "internship",
    "roles": ["product designer", "ux designer"],
    "location": "remote, Lisbon",
    "skills": ["Figma", "prototyping", "user research"],
    "experience": [
        "Design intern, Northwind (2025): redesigned onboarding, sign-up completion up 18%",
        "Freelance designer (2024): 12 client sites",
    ],  # 2024 and 12 aren't in the resume
    "projects": ["Shelf: a library app for small reading groups"],
    "education": "BDes Interaction Design (final year)",
    "wins": ["Sign-up completion up 18% at Northwind", "Tested with 40+ readers"],  # 40: not in the resume
}


class Brain:
    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    def ask(self, prompt, schema, **kw):
        self.calls.append(kw)
        if self.fail:
            raise BrainError("budget", "today's budget is used up")
        assert "Northwind" in prompt
        return CARD


@pytest.fixture
def brain(monkeypatch):
    b = Brain()
    monkeypatch.setattr(jobs, "get_brain", lambda s: b)
    monkeypatch.setattr(jobs, "run_once", lambda fn, job_id: fn())  # the background job, right away
    return b


def upload(client, kind="resume"):
    data = base64.b64encode(RESUME.encode()).decode()
    return client.post("/api/docs", json={"name": "resume.txt", "kind": kind, "data_b64": data})


def test_a_resume_becomes_a_card_in_the_background(client, conn, brain):
    db.set_profile(conn, "about", {"location": "Porto"})  # the user's own answer
    upload(client)
    got = client.get("/api/profile").json()
    assert got["state"] == "ready" and got["has_resume"]
    assert brain.calls == [{"light": True, "kind": "profile"}]
    text = got["text"]
    assert "**Who:** Final-year interaction design student" in text and "## Projects" in text
    # links come from the resume itself, never the model; a mail address isn't a link
    assert "- https://robin.example/work" in text and "- https://github.com/robin-example" in text
    assert "robin@example.com" not in text
    assert "Sign-up completion up 18%" in text and "40+" not in text  # a number it made up drops the line
    assert "Freelance" not in text  # ...and when even the role's own line doesn't hold up, the whole job
    assert profile._clean(["Intern, Acme (2025): grew sign-ups 300%"], 4, RESUME, head=True) == [
        "Intern, Acme (2025)"
    ]
    # empty answers are filled from the resume; the user's own location stays
    about = db.get_profile(conn, "about")
    assert about == {"location": "Porto", "level": "internship", "roles": "product designer, ux designer"}


def test_what_you_said_youre_after_wins_over_the_resume(client, conn, brain):
    db.set_profile(conn, "about", {"looking_for": "a junior role in ux research"})
    upload(client)
    about = db.get_profile(conn, "about")
    assert "level" not in about and "roles" not in about and about["location"] == "remote, Lisbon"
    assert profile.path(get_settings()).parent.name == "memory"  # markdown in the memory folder


def test_other_documents_dont_spend_anything(client, brain):
    upload(client, kind="notes")
    assert brain.calls == [] and client.get("/api/profile").json()["state"] == "none"
    assert client.post("/api/profile/rebuild").status_code == 400  # no resume to read


def test_notes_survive_a_rebuild_and_every_ask_reads_the_card(client, conn, brain):
    s = get_settings()
    tools.remember(s, conn, "note", "prefers async teams; no calls before 10am")
    upload(client)
    tools.remember(s, conn, "note", "learning SwiftUI")
    client.post("/api/profile/rebuild")
    text = profile.read(s)
    assert text.count("## Notes") == 1
    assert "- prefers async teams; no calls before 10am\n- learning SwiftUI" in text
    prompt = runner.system_prompt(s, conn)
    assert "**Who:** Final-year interaction design student" in prompt and "learning SwiftUI" in prompt
    assert "# Profile card" not in prompt and "Written from" not in prompt


def test_your_edits_are_the_card(client, conn):
    client.put(
        "/api/profile", json={"text": "# Profile card\n\n**Who:** a designer who writes\n\n## Notes\n- tea"}
    )
    assert "a designer who writes" in runner.system_prompt(get_settings(), conn)
    assert profile.notes(profile.read(get_settings())) == "- tea"


def test_a_failed_call_says_so_and_writes_nothing(client, monkeypatch):
    monkeypatch.setattr(jobs, "get_brain", lambda s: Brain(fail=True))
    monkeypatch.setattr(jobs, "run_once", lambda fn, job_id: fn())
    upload(client)
    got = client.get("/api/profile").json()
    assert got["state"] == "error" and "budget" in got["error"] and got["text"] == ""
