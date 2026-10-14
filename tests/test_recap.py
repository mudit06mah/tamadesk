"""The recap's picks for tomorrow point at todos you already have, never a reworded copy of one; an
early recap is a recap so far; and misclicks can be taken back (a tossed draft, a dismissed tip)."""

from datetime import datetime

from tamadesk.api.routes import today_rows
from tamadesk.core import db
from tamadesk.life import actions, suggest, today, writer


class Brain:
    def __init__(self, picks):
        self.picks, self.prompt = picks, ""

    def ask(self, prompt, schema, **kw):
        self.prompt = prompt
        return {"headline": "One solid win", "recap": "Nice.", "tomorrow": self.picks}


def test_tomorrow_points_at_open_todos_and_never_at_done_ones(conn):
    dl = actions.add_todo(conn, "Deep Learning week 1")
    tt = actions.add_todo(conn, "Tiktok setup")
    rec = actions.add_todo(conn, "write the recommendation")
    actions.complete_todo(conn, rec)
    brain = Brain([{"todo": dl, "text": "Start Deep Learning week 1"},  # reworded: the real title wins
                   {"todo": 0, "text": "write the recommendation"},  # already done today
                   {"todo": 999, "text": "Knock out Tiktok Setup"},  # no such id, but it names an open todo
                   {"todo": 0, "text": "Stretch for ten minutes"},  # a real new idea
                   {"todo": tt, "text": "Tiktok setup"}])  # fmt: skip
    r = writer.recap(
        conn, brain, today_rows(conn), now=datetime.now().astimezone().replace(hour=16, minute=35)
    )
    assert r["tomorrow"] == [
        {"text": "Deep Learning week 1", "todo_id": dl},
        {"text": "Tiktok setup", "todo_id": tt},
        {"text": "Stretch for ten minutes", "todo_id": None},
    ]
    assert r["so_far"] and "recap it so far" in brain.prompt and f"[open #{dl}, added today]" in brain.prompt
    db.event(conn, "recap", detail=__import__("json").dumps(r))
    actions.complete_todo(conn, dl)  # done after the recap: it shows done, not "on your list"
    picks = next(e for e in today.day(conn)["timeline"] if e["kind"] == "recap")["recap"]["tomorrow"]
    assert [p["status"] for p in picks] == ["done", "open", None]


def test_a_late_recap_is_the_whole_day(conn):
    actions.add_todo(conn, "x")
    brain = Brain([])
    r = writer.recap(conn, brain, today_rows(conn), now=datetime.now().astimezone().replace(hour=21))
    assert not r["so_far"] and "so far" not in brain.prompt


def test_misclicks_come_back(client, conn):
    d = actions.add_draft(conn, ask="t", subject="Hi", body="Hi Sam, [link]", to_email="s@example.com")
    client.post(f"/api/mail/{d}/drop")
    client.post(f"/api/mail/{d}/restore")
    assert conn.execute("SELECT status FROM drafts WHERE id = ?", (d,)).fetchone()[0] == "draft"
    [tip] = suggest.open_for(conn, "draft", d)
    suggest.act(conn, tip["id"], "dismiss")
    suggest.act(conn, tip["id"], "undo")
    assert [s["id"] for s in suggest.open_for(conn, "draft", d)] == [tip["id"]]
