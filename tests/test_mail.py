from typing import ClassVar

import pytest

from tamadesk.core import db
from tamadesk.core.config import get_settings
from tamadesk.life import mail
from tamadesk.life.actions import add_draft


class FakeSMTP:
    sent: ClassVar[list] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        assert pw == "abcdabcdabcdabcd"

    def send_message(self, m):
        FakeSMTP.sent.append(m)


@pytest.fixture
def setup(client, monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    client.put(
        "/api/mail/setup",
        json={"address": "me@gmail.com", "from_name": "Me", "app_password": "abcd abcd abcd abcd"},
    )
    return client


def _draft(**kw):
    conn = db.connect(get_settings().db_path)
    rid = add_draft(
        conn, **{"ask": "t", "subject": "Hi", "body": "Hello there", "to_email": "ana@x.dev"} | kw
    )
    conn.close()
    return rid


def test_password_is_private_and_dry_run_goes_to_me(setup):
    s = get_settings()
    assert (s.home / "secrets.json").stat().st_mode & 0o777 == 0o600
    assert "abcd" not in setup.get("/api/mail").text
    r = setup.post(f"/api/mail/{_draft(item_id=7)}/send", json={}).json()
    assert r["dry_run"] and "me@gmail.com" in r["to"]
    m = FakeSMTP.sent[0]
    assert (
        m["Subject"].startswith("[dry run → ana@x.dev]") and mail.OPT_OUT in m.get_content()
    )  # outreach: opt-out
    assert setup.get("/api/mail?status=sent").json()["items"][0]["subject"] == "Hi"


def test_guessed_address_needs_check_and_cap_holds(setup, monkeypatch):
    rid = _draft(email_sure=False)
    assert "guessed" in setup.post(f"/api/mail/{rid}/send", json={}).json()["detail"]
    assert setup.post(f"/api/mail/{rid}/send", json={"verified": True}).status_code == 200
    monkeypatch.setattr(get_settings().mail, "daily_cap", 1)
    assert "cap" in setup.post(f"/api/mail/{_draft()}/send", json={}).json()["detail"]


def test_typing_your_own_address_counts_as_checked(setup):
    rid = _draft(email_sure=False)
    setup.patch(
        f"/api/mail/{rid}", json={"subject": "Hi", "body": "b", "to_name": "", "to_email": "real@x.dev"}
    )
    assert setup.post(f"/api/mail/{rid}/send", json={}).status_code == 200
