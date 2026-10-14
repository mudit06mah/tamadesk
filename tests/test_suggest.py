"""Only-you suggestions: regex rules on mail and drafts, done / dismissed / undo, XP only for real
progress, and they show up on Today rather than in a list of their own."""

from datetime import datetime, timedelta

import pytest

from tamadesk.life import actions, suggest, today

WED = datetime(2026, 10, 7, 10, 0)


def xp(conn) -> int:
    return conn.execute("SELECT coalesce(sum(xp), 0) FROM events WHERE kind LIKE 'suggestion%'").fetchone()[0]


def rules(conn, target, tid) -> dict:
    return {s["rule"]: s for s in suggest.open_for(conn, target, tid)}


def test_questions_and_deadlines_are_read_with_plain_rules():
    assert suggest.question("Thanks for the note! Could you do Thursday or Friday afternoon? Best, R") == (
        "Could you do Thursday or Friday afternoon?"
    )
    assert suggest.question("Great, talk soon. No rush.") is None
    assert suggest.deadline("Please send the signed form by Friday.", WED) == datetime(2026, 10, 9, 0, 0)
    assert suggest.deadline("We need it within 48 hours", WED) == WED + timedelta(hours=48)
    assert suggest.deadline("Can you confirm by end of day?", WED) == datetime(2026, 10, 7, 17, 0)
    assert suggest.deadline("I bought it by accident, by the way", WED) is None


def test_a_draft_gets_the_things_only_you_can_do(conn):
    job = conn.execute(
        "INSERT INTO items (module, ext_id, source, title, data, status) VALUES "
        "('jobs', 'n', 'x', 'Product Designer, Northwind', '{\"company\": \"Northwind\"}', 'saved')"
    ).lastrowid
    d = actions.add_draft(conn, ask="t", subject="Hi", body="Hi,\n\nI hope this email finds you well. I'd love to "
                          "apply. My portfolio: [link]", to_name="Jordan Lee", to_email="jordan@northwind.example",
                          email_sure=False, item_id=job)  # fmt: skip
    got = rules(conn, "draft", d)
    assert set(got) == {"guessed_address", "why_company", "personal_detail"}
    assert got["personal_detail"]["text"].startswith("Fill in [link]")
    assert got["guessed_address"]["required"]


def test_dismissed_never_comes_back_and_the_address_check_cant_be_skipped(conn):
    d = actions.add_draft(conn, ask="t", subject="Hi", body="Hi Alex, [your line]", to_email="a@b.example",
                          email_sure=False)  # fmt: skip
    got = rules(conn, "draft", d)
    suggest.act(conn, got["personal_detail"]["id"], "dismiss")
    assert "personal_detail" not in rules(conn, "draft", d)
    with pytest.raises(ValueError):
        suggest.act(conn, got["guessed_address"]["id"], "dismiss")
    assert suggest.act(conn, got["guessed_address"]["id"], "done") == {"xp": 0}  # your word, not proof
    assert conn.execute("SELECT email_sure FROM drafts WHERE id = ?", (d,)).fetchone()[0] == 1
    assert rules(conn, "draft", d) == {}


def test_xp_only_for_real_progress_and_undo_takes_it_back(conn):
    d = actions.add_draft(
        conn, ask="t", subject="Hi", body="Hi Sam, here is my site: [link]", to_email="s@x.example"
    )
    tip = rules(conn, "draft", d)["personal_detail"]
    assert suggest.act(conn, tip["id"], "done") == {"xp": 0}  # ticked, but [link] is still there
    suggest.act(conn, tip["id"], "undo")
    conn.execute("UPDATE drafts SET body = 'Hi Sam, here is my site: https://example.com' WHERE id = ?", (d,))
    # undone: it never re-ticks itself, but ticking it now is real (the placeholder is gone)
    assert set(rules(conn, "draft", d)) == {"personal_detail"} and xp(conn) == 0
    assert suggest.act(conn, tip["id"], "done") == {"xp": 3}
    suggest.act(conn, tip["id"], "undo")
    e = actions.add_draft(conn, ask="t", subject="Hi", body="Hi Sam, [link]", to_email="s@x.example")
    tip = rules(conn, "draft", e)["personal_detail"]
    conn.execute("UPDATE drafts SET body = 'Hi Sam, https://example.com' WHERE id = ?", (e,))
    assert rules(conn, "draft", e) == {} and xp(conn) == 3
    assert suggest.act(conn, tip["id"], "undo") == {"xp": -3} and xp(conn) == 0


def test_a_question_resolves_when_you_reply_in_the_thread(conn):
    sent = actions.add_draft(conn, ask="t", subject="Hello", body="b", to_email="riley@contoso.example")
    conn.execute(
        "UPDATE drafts SET status = 'sent', sent_at = datetime('now', '-2 days') WHERE id = ?", (sent,)
    )
    m = conn.execute(
        "INSERT INTO inbox (message_id, draft_id, kind, from_addr, from_name, subject, snippet, received_at) VALUES "
        "('<1@x>', ?, 'interview', 'riley@contoso.example', 'Riley', 'Re: Hello', ?, datetime('now', '-1 hours'))",
        (sent, "Thanks! Could you do a call Thursday? Please confirm by Friday."),
    ).lastrowid
    got = rules(conn, "inbox", m)
    assert set(got) == {"direct_question", "deadline"}
    at = suggest.remind(conn, got["deadline"]["id"])
    assert conn.execute("SELECT due_at FROM reminders").fetchone()[0] == at < got["deadline"]["data"]["due"]

    reply = actions.add_draft(
        conn, ask="t", subject="Re: Hello", body="Thursday works", parent_id=sent, kind="reply"
    )
    conn.execute("UPDATE drafts SET status = 'sent', sent_at = datetime('now') WHERE id = ?", (reply,))
    assert rules(conn, "inbox", m) == {} and xp(conn) == 6


def test_done_suggestions_flow_into_today_not_a_separate_list(client, conn):
    actions.add_draft(
        conn, ask="t", subject="Hi", body="Hi, [link]", to_name="Alex", to_email="alex@x.example"
    )
    row = next(e for e in client.get("/api/today").json()["needs_you"] if e["key"].startswith("n:draft"))
    [tip] = row["suggestions"]
    assert client.get("/api/mail").json()["items"][0]["suggestions"][0]["id"] == tip["id"]
    client.post(f"/api/suggestions/{tip['id']}/done")
    did = [e for e in today.day(conn)["timeline"] if e["kind"] == "did"]
    assert [e["ref"]["suggestion"] for e in did] == [tip["id"]]
    client.post(f"/api/suggestions/{tip['id']}/undo")
    assert not [e for e in today.day(conn)["timeline"] if e["kind"] == "did"]
    assert today.brief(conn)["needs_you"][0]["only_you"] == [tip["text"]]


def test_claude_is_asked_only_on_a_click_and_only_once(conn):
    d = actions.add_draft(conn, ask="t", subject="Plan", body="Hi Alex, sounds good. Talk Thursday.", to_name="Alex",
                          to_email="alex@x.example")  # fmt: skip
    assert rules(conn, "draft", d) == {} and not suggest.asked(conn, "draft", d)

    class Brain:
        calls = 0

        def ask(self, prompt, schema, **kw):
            Brain.calls += 1
            assert kw == {"light": True, "kind": "suggest"}
            return {"suggestions": ["Confirm which Thursday you mean"]}

    out = suggest.ask_claude(conn, Brain(), "draft", d)
    assert [s["text"] for s in out] == ["Confirm which Thursday you mean"] and suggest.asked(conn, "draft", d)
    assert Brain.calls == 1
