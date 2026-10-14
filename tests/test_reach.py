"""Reaching the desk from anywhere: mail yourself "td: …", deadline feeds (school, CFPs), any mail
provider, export/import, starting at login. Plus quieter tabs."""

import json
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tamadesk.cli import app as cli
from tamadesk.core import db, service
from tamadesk.core.config import get_settings
from tamadesk.life import calendar, capture, inbox, mail
from tamadesk.modules import engine, sources, spec
from tamadesk.modules.sources import Item

ME = "me@example.com"


@pytest.fixture
def conn(client):
    s = get_settings()
    s.mail.address = ME
    c = db.connect(s.db_path)
    yield c
    c.close()


def _mail(frm: str, subject: str) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, ME, subject, f"<{abs(hash(subject))}@x>"
    m.set_content("sent from my phone")
    return m


def test_mailing_yourself_td_is_a_quick_capture(conn):
    s = get_settings()
    assert inbox.self_capture(s, _mail(ME, "td: buy stamps")) == "todo buy stamps"
    assert (
        inbox.self_capture(s, _mail(ME, "td: remind me to call mom at 6pm")) == "remind me to call mom at 6pm"
    )
    assert inbox.self_capture(s, _mail(ME, "log: ran 5k")) == "log ran 5k"
    assert inbox.self_capture(s, _mail("someone@example.com", "td: wire money")) is None  # only from yourself
    assert inbox.self_capture(s, _mail(ME, "lunch?")) is None


def test_a_deadline_feed_becomes_todos_that_follow_it(conn):
    s = get_settings()
    mail.set_secret(
        s, calendar.DEADLINE_SECRET, [{"url": "https://school.example/feed.ics", "tag": "school"}]
    )
    when = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y%m%d")

    def feed(*essays: tuple[str, str]) -> bytes:
        body = "".join(f"BEGIN:VEVENT\r\nUID:{u}@school.example\r\nDTSTAMP:20261001T000000Z\r\n"
                       f"DTSTART;VALUE=DATE:{d}\r\nSUMMARY:Essay {u} due\r\nEND:VEVENT\r\n" for u, d in essays)  # fmt: skip
        return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{body}END:VCALENDAR\r\n".encode()

    assert calendar.sync_deadlines(s, conn, get=lambda url, **kw: feed(("1", when), ("2", when))) == 2
    rows = conn.execute("SELECT title, tags, due_at FROM todos ORDER BY id").fetchall()
    assert [r["title"] for r in rows] == ["Essay 1 due", "Essay 2 due"] and rows[0]["tags"] == "school"
    assert calendar.sync_deadlines(s, conn, get=lambda url, **kw: feed(("1", when))) == 0  # essay 2 dropped
    assert dict(conn.execute("SELECT title, status FROM todos").fetchall()) == {"Essay 1 due": "open",
                                                                                "Essay 2 due": "dropped"}  # fmt: skip
    assert calendar.status(s, conn)["deadline_feeds"] == [{"tag": "school", "host": "school.example"}]


def test_cfps_carry_their_deadline_into_a_todo(client, conn, monkeypatch):
    soon = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    confs = [{"name": "DevConf", "url": "https://devconf.example", "cfpUrl": "https://devconf.example/cfp",
              "cfpEndDate": soon, "startDate": "2027-03-01", "city": "Lisbon", "country": "Portugal"},
             {"name": "OldConf", "url": "https://old.example", "cfpEndDate": past}]  # fmt: skip
    monkeypatch.setattr(
        sources, "get_json", lambda url, **kw: confs if "/2026/" in url or "/2027/" in url else []
    )
    items = sources.cfp("javascript")
    assert [i.title for i in items] == [f"DevConf: CFP closes {soon}"] and items[0].data["deadline"] == soon
    m = spec.from_template("cfps", {"topics": "javascript"})
    engine.run(conn, m)
    iid = conn.execute("SELECT id FROM items").fetchone()[0]
    due = client.post(f"/api/items/{iid}/todo").json()["due_at"]
    assert (
        datetime.fromisoformat(due).replace(tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H") == f"{soon} 17"
    )


def test_any_mail_provider(monkeypatch):
    s = get_settings()
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            calls.append((host, port))

        def starttls(self):
            calls.append("starttls")

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    s.mail.provider = "icloud"
    mail._smtp(s)
    s.mail.provider, s.mail.smtp_host, s.mail.smtp_port, s.mail.imap_host = (
        "custom",
        "smtp.example",
        465,
        "imap.example",
    )
    mail._smtp(s)
    assert mail.hosts(s)[0] == "imap.example"
    s.mail.provider = "gmail"
    assert calls == [("smtp.mail.me.com", 587), "starttls", ("smtp.example", 465)]


def test_unseen_tab_items_quietly_expire(conn, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: [Item(ext_id="a", title="old news")])
    m = spec.Module(id="news", name="News", sources=[{"type": "fake"}], expire_days=3)
    engine.run(conn, m)
    conn.execute("UPDATE items SET created_at = datetime('now', '-4 days')")
    engine.run(conn, m)
    assert conn.execute("SELECT status FROM items").fetchone()[0] == "gone"


def test_export_and_import_move_your_desk_without_secrets(client, tmp_path_factory):
    run = CliRunner().invoke
    mail.set_secret(get_settings(), "gmail_app_password", "secret")
    out = tmp_path_factory.mktemp("elsewhere") / "desk.zip"
    assert run(cli, ["export", str(out)]).exit_code == 0
    import zipfile

    names = zipfile.ZipFile(out).namelist()
    assert "tamadesk.db" in names and "secrets.json" not in names
    assert run(cli, ["import", str(out)]).exit_code == 1  # this desk already has data
    assert run(cli, ["import", str(out), "--force"]).exit_code == 0
    assert (get_settings().home / "tamadesk.before-import.db").exists()


def test_starting_at_login_on_each_system(tmp_path):
    f, text, cmds = service.plan("linux", tmp_path)
    assert f == tmp_path / ".config/systemd/user/tamadesk.service" and "-m tamadesk serve" in text
    assert cmds[-1] == ["systemctl", "--user", "enable", "--now", "tamadesk"]
    f, text, _ = service.plan("darwin", tmp_path)
    assert f.name == "dev.tamadesk.plist" and "<string>serve</string>" in text
    f, text, cmds = service.plan("win32", tmp_path)
    assert f.name == "tamadesk.vbs" and "pythonw.exe" in text and cmds == []


def test_the_ask_box_and_the_desk_agree_on_what_is_free():
    """Every shortcut the desk understands is sent to it by the Ask box (instant, no AI), and a real
    question still goes to the assistant."""
    ts = (Path(__file__).parents[1] / "frontend/src/AskStore.tsx").read_text()
    rx = re.compile(re.search(r"export const FREE =\s*/(.+)/i", ts).group(1), re.IGNORECASE)
    for example in ["todo x", "remind me to x at 6pm", "done x", "finished x", "move x to fri", "push x to mon",
                    "waiting on x", "waiting for x", "meeting x at 3pm", "call mom at 6", "focus 25", "focus",
                    "next", "what's next?", "?", "log x", "> x", "remove x", "cancel the x reminder"]:  # fmt: skip
        assert rx.match(example), example
        assert capture.parse(example).kind != "log" or example.startswith(("log", ">")), example
    for question in [
        "find me design internships",
        "what's the weather like in Lisbon?",
        "next week's plan please",
    ]:
        assert not rx.match(question), question
    assert json.dumps(capture.VERBS)  # the list the docs point to
