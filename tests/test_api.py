from tamadesk.api.jobs import ring_due
from tamadesk.core import db
from tamadesk.core.config import get_settings


def test_new_game_then_state(client):
    assert client.get("/api/state").json()["onboarded"] is False
    r = client.post(
        "/api/onboarding", json={"about": {"name": "Sam"}, "companion": {"species": "blob", "name": "Mochi"}}
    )
    assert r.status_code == 200
    st = client.get("/api/state").json()
    assert st["onboarded"] and st["companion"]["name"] == "Mochi"
    assert st["progress"]["xp"] == 50
    # replaying the wizard doesn't grant the bonus twice
    client.post(
        "/api/onboarding", json={"about": {"name": "Sam"}, "companion": {"species": "bot", "name": "B"}}
    )
    assert client.get("/api/state").json()["progress"]["xp"] == 50


def test_unknown_companion_rejected(client):
    r = client.post("/api/onboarding", json={"about": {}, "companion": {"species": "dragon", "name": "x"}})
    assert r.status_code == 400


def test_capture_todo_done_and_undo_xp(client):
    t = client.post("/api/capture", json={"text": "todo write tests"}).json()
    assert t["kind"] == "todo"
    assert client.post(f"/api/todos/{t['id']}/done").json()["xp"] == 10
    # double "done" doesn't double count
    assert client.post(f"/api/todos/{t['id']}/done").json()["xp"] == 0
    st = client.get("/api/state").json()
    assert st["progress"]["xp"] == 10 and len(st["today"]["done"]) == 1
    client.post(f"/api/todos/{t['id']}/undo")
    st = client.get("/api/state").json()
    assert st["progress"]["xp"] == 0 and len(st["today"]["open"]) == 1


def test_log_entry_counts_today(client):
    r = client.post("/api/capture", json={"text": "shipped the onboarding wizard"}).json()
    assert r["kind"] == "log" and r["xp"] == 5
    st = client.get("/api/state").json()
    assert [e["body"] for e in st["today"]["log"]] == ["shipped the onboarding wizard"]
    assert st["progress"]["streak_days"] == 1


def test_due_reminder_rings_then_dismiss(client, monkeypatch):
    monkeypatch.setattr("tamadesk.api.jobs.notify", lambda *a: None)
    conn = db.connect(get_settings().db_path)
    conn.execute("INSERT INTO reminders (text, due_at) VALUES ('stretch', datetime('now', '-1 minute'))")
    conn.execute("INSERT INTO reminders (text, due_at) VALUES ('later', datetime('now', '+1 hour'))")
    conn.close()
    ring_due()
    rem = {r["text"]: r for r in client.get("/api/state").json()["reminders"]}
    assert rem["stretch"]["status"] == "fired" and rem["later"]["status"] == "pending"
    assert client.post(f"/api/reminders/{rem['stretch']['id']}/dismiss").json()["xp"] == 3


def test_recap_needs_something(client):
    assert client.post("/api/recap").status_code == 400


def test_clean_strips_dashes():
    from tamadesk.life.writer import clean

    assert clean("fixed it — finally") == "fixed it, finally"
    assert clean("a–b") == "a, b"


def test_set_one_about_field_keeps_the_rest(client):
    client.post(
        "/api/onboarding", json={"about": {"name": "Sam"}, "companion": {"species": "blob", "name": "B"}}
    )
    about = client.post("/api/about", json={"key": "interests", "value": " devops, games "}).json()
    assert about == {"name": "Sam", "interests": "devops, games"}
    assert client.post("/api/about", json={"key": "Bad Key!", "value": "x"}).status_code == 422
