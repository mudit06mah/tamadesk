"""Journeys: a send moves the item along, the inbox matches what comes back, Up next says what's due."""

import json
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest
from test_mail import FakeSMTP

from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import inbox, mail, pipeline, upnext
from tamadesk.life.actions import add_draft
from tamadesk.modules import sources, spec
from tamadesk.modules.sources import Item


@pytest.fixture
def desk(client, monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    client.put("/api/mail/setup", json={"address": "me@gmail.com", "from_name": "Me",
                                        "app_password": "abcd abcd abcd abcd", "dry_run": False})  # fmt: skip
    conn = db.connect(get_settings().db_path)
    job = conn.execute(
        "INSERT INTO items (module, ext_id, source, title, url, data, status, decided_at) "
        "VALUES ('jobs', 'x', 'company_jobs', 'Designer at Everai', 'https://jobs.ashbyhq.com/everai/123', ?, "
        "'saved', datetime('now', '-5 days'))",
        (json.dumps({"apply_url": "https://jobs.ashbyhq.com/everai/123/application", "company": "Everai"}),),
    ).lastrowid
    yield client, conn, job
    conn.close()


def _msg(frm: str, subject: str, body: str, refs: str = "") -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "me@gmail.com", subject
    m["Message-ID"] = f"<{abs(hash(subject + body))}@x>"
    m["Date"] = "Mon, 05 Oct 2026 10:00:00 +0000"
    if refs:
        m["In-Reply-To"] = m["References"] = refs
    m.set_content(body)
    return m


def test_stages_only_move_forward_unless_you_say_so(desk):
    _, conn, job = desk
    assert pipeline.set_stage(conn, job, "replied")
    assert not pipeline.set_stage(conn, job, "applied")  # a late "thanks for applying" doesn't undo a reply
    assert pipeline.set_stage(conn, job, "applied", manual=True)
    assert conn.execute("SELECT stage FROM items WHERE id = ?", (job,)).fetchone()[0] == "applied"
    assert conn.execute("SELECT count(*) FROM events WHERE kind LIKE 'stage_%'").fetchone()[0] == 2


def test_send_threads_the_follow_up_and_the_reply_is_matched(desk):
    client, conn, job = desk
    first = add_draft(conn, ask="t", subject="Design role", body="Hi", to_email="ana@everai.com", item_id=job)
    client.post(f"/api/mail/{first}/send", json={})
    assert conn.execute("SELECT stage FROM items WHERE id = ?", (job,)).fetchone()[0] == "emailed"
    sent_id = conn.execute("SELECT message_id FROM drafts WHERE id = ?", (first,)).fetchone()[0]

    nudge = add_draft(conn, ask="t", subject="x", body="Just checking in", parent_id=first, kind="followup")
    row = conn.execute("SELECT to_email, item_id FROM drafts WHERE id = ?", (nudge,)).fetchone()
    assert tuple(row) == ("ana@everai.com", job)  # inherited from the thread
    client.post(f"/api/mail/{nudge}/send", json={})
    m = FakeSMTP.sent[-1]
    assert (
        m["In-Reply-To"] == sent_id
        and m["Subject"] == "Re: Design role"
        and mail.OPT_OUT not in m.get_content()
    )

    reply = _msg(
        "Ana <ana@everai.com>",
        "Re: Design role",
        "Could we schedule a call next week?\n\nOn Mon, Me wrote:\n> Hi",
        sent_id,
    )
    hit = inbox.match(conn, "me@gmail.com", reply)
    assert hit["kind"] == "interview" and hit["draft_id"] == first and "On Mon" not in hit["snippet"]
    assert inbox.record(conn, reply["Message-ID"], hit, "2026-10-05 10:00:00")
    assert conn.execute("SELECT stage FROM items WHERE id = ?", (job,)).fetchone()[0] == "interview"
    assert client.get("/api/next").json()[0]["action"] == "answer"
    assert client.get("/api/mail?status=sent").json()["items"][-1]["heard"] == "interview"


def test_portal_mail_matches_the_pipeline_and_strangers_are_ignored(desk):
    _, conn, job = desk
    ats = _msg(
        "Everai Hiring <no-reply@ashbyhq.com>",
        "Thanks for applying to Everai",
        "We have received your application.",
    )
    hit = inbox.match(conn, "me@gmail.com", ats)
    assert hit["item_id"] == job and hit["kind"] == "applied"
    newsletter = _msg("news@techdigest.io", "This week", "Startups like Everai raised money.")
    assert inbox.match(conn, "me@gmail.com", newsletter) is None  # a passing mention isn't about you
    assert inbox.match(conn, "me@gmail.com", _msg("friend@gmail.com", "lunch?", "tacos")) is None


def test_inbox_check_reads_only_and_stores_only_matches(desk):
    _, conn, _ = desk
    msgs = [_msg("Everai <jobs@everai.com>", "Update", "Unfortunately we decided to move forward with others."),
            _msg("spam@deals.com", "50% off", "buy now")]  # fmt: skip

    class FakeIMAP:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            assert pw == "abcdabcdabcdabcd"

        def select(self, box, readonly=False):
            assert readonly

        def search(self, *a):
            return "OK", [b"1 2"]

        def fetch(self, num, what):
            assert "PEEK" in what  # never marks anything read
            return "OK", [(b"1", msgs[int(num) - 1].as_bytes())]

    found = inbox.check(get_settings(), conn, connect=FakeIMAP)
    assert [f["kind"] for f in found] == ["rejected"]
    assert conn.execute("SELECT count(*) FROM inbox").fetchone()[0] == 1
    assert inbox.check(get_settings(), conn, connect=FakeIMAP) == []  # seen once, never again


def test_follow_ups_wait_four_business_days_and_can_be_switched_off(desk):
    _, conn, job = desk
    d = add_draft(conn, ask="t", subject="Hi", body="b", to_email="a@everai.com", item_id=job)
    conn.execute(
        "UPDATE drafts SET status='sent', sent_at='2026-10-02 09:00:00', message_id='<m1@x>' WHERE id=?", (d,)
    )
    fri, tue, thu = (datetime(2026, 10, day, 12, tzinfo=UTC) for day in (2, 6, 8))
    assert upnext.business_days_since("2026-10-02 09:00:00", tue) == 2  # the weekend doesn't count
    assert upnext.followups_due(conn, fri) == [] and upnext.followups_due(conn, tue) == []
    assert [x["id"] for x in upnext.followups_due(conn, thu)] == [d]
    conn.execute("UPDATE drafts SET followup_off = 1 WHERE id = ?", (d,))
    assert upnext.followups_due(conn, thu) == []


def test_up_next_gathers_drafts_and_stale_kept_jobs(desk):
    client, conn, _ = desk
    add_draft(conn, ask="t", subject="Hi", body="b", to_email="")
    kinds = [x["kind"] for x in client.get("/api/next").json()]
    assert kinds == ["drafts", "kept"]


def test_empty_address_is_not_called_guessed(desk):
    _, conn, _ = desk
    d = add_draft(conn, ask="t", subject="Hi", body="b", to_email="", email_sure=False)
    assert conn.execute("SELECT email_sure FROM drafts WHERE id = ?", (d,)).fetchone()[0] == 1


def test_youtube_feed_brings_the_description():
    xml = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
      <entry><id>yt:video:abc</id><title>Rust in 100s</title><link href="https://www.youtube.com/watch?v=abcdefghijk"/>
      <media:group><media:description>A fast tour of Rust ownership.</media:description></media:group></entry></feed>"""
    assert sources.parse_feed(xml)[0].body == "A fast tour of Rust ownership."
    assert sources.transcript("https://example.com/not-a-video") == ""


def test_voice_can_be_steered(client):
    conn = db.connect(get_settings().db_path)
    db.set_profile(
        conn,
        "voice",
        {"summary": "s", "traits": ["warm"], "do": ["short"], "dont": ["jargon"], "phrases": []},
    )
    conn.close()
    r = client.put("/api/voice", json={"do": [], "rules": ["  never say synergy ", ""]}).json()
    assert r["voice"]["do"] == [] and r["voice"]["dont"] == ["jargon"] and r["rules"] == ["never say synergy"]


def test_rename_a_tab_without_refetching(client, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: [Item(ext_id="a", title="A")])
    spec.save(get_settings(), spec.Module(id="j", name="J", sources=[{"type": "fake", "query": "q"}]))
    assert client.patch("/api/modules/j/name", json={"name": " Dream jobs "}).json()["name"] == "Dream jobs"
    m = spec.get(get_settings(), "j")
    assert m.name == "Dream jobs" and m.sources[0].model_dump().get("query") == "q"
    assert client.patch("/api/modules/j/name", json={"name": "x" * 40}).status_code == 422


def test_a_running_ask_can_be_stopped(tmp_path):
    import threading

    from tamadesk.assistant import runner

    s = type("S", (), {"home": tmp_path})()
    out: list[dict] = []
    t = threading.Thread(target=lambda: out.extend(runner.stream(s, ["sleep", "30"], key=7)))
    t.start()
    while 7 not in runner.RUNNING:
        pass
    assert runner.stop(7) and not runner.stop(8)
    t.join(5)
    assert out == [{"type": "stopped"}] and 7 not in runner.RUNNING


def test_a_kept_video_never_turns_platform_mail_into_news(desk):
    _, conn, _ = desk
    conn.execute("INSERT INTO items (module, ext_id, source, title, url, status) "
                 "VALUES ('videos', 'v', 'rss', 'A talk', 'https://www.youtube.com/watch?v=abcdefghijk', 'saved')")  # fmt: skip
    tos = _msg(
        "YouTube <no-reply@youtube.com>", "Terms of Service reminder", "Quarterly reminder about our terms."
    )
    assert inbox.match(conn, "me@gmail.com", tos) is None
