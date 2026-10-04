import pytest

from tamadesk.core import db
from tamadesk.core.config import Settings
from tamadesk.life import memory


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.migrate(c)
    return c


@pytest.fixture
def s(tmp_path):
    return Settings(home=tmp_path)


def _chat(conn, text, role="user", day="2026-09-03"):
    cid = conn.execute("INSERT INTO chats (title) VALUES ('t')").lastrowid
    conn.execute(
        "INSERT INTO messages (chat_id, role, text, created_at) VALUES (?, ?, ?, ?)",
        (cid, role, text, f"{day} 12:00:00"),
    )
    return cid


class FakeBrain:
    name = "fake"

    def ask(self, prompt, schema, *, system="", light=False, kind="brain"):
        assert light and kind == "memory" and "omakase" in prompt
        return {"summary": "Planned food and fixed a bug.", "facts": [
            {"text": "Wants to try the omakase counter Sushi Ishii near the office.",
             "tags": "japanese food dish cuisine restaurant dinner"}]}  # fmt: skip


def test_everything_is_indexed_and_cascades(conn):
    cid = _chat(conn, "remember the omakase place, Sushi Ishii, I want to go there")
    conn.execute("INSERT INTO log_entries (body) VALUES ('fixed the flaky test')")
    conn.execute("INSERT INTO todos (title) VALUES ('book a table')")
    kinds = {r[0] for r in conn.execute("SELECT kind FROM recall")}
    assert kinds == {"chat_user", "log", "todo"}
    conn.execute("DELETE FROM chats WHERE id = ?", (cid,))  # deleting a chat forgets its messages
    assert {r[0] for r in conn.execute("SELECT kind FROM recall")} == {"log", "todo"}


def test_the_sushi_scenario(conn, s):
    _chat(conn, "remember the omakase place, Sushi Ishii, I want to go there")
    # raw text alone doesn't know it's japanese food
    assert memory.search(conn, "japanese dish") == []
    assert memory.pending_days(conn) == ["2026-09-03"]
    memory.digest(s, conn, FakeBrain(), "2026-09-03")
    hits = memory.search(conn, "that japanese dish I wanted to try")
    assert hits[0]["kind"] == "fact" and "Sushi Ishii" in hits[0]["text"] and hits[0]["day"] == "2026-09-03"
    assert memory.pending_days(conn) == []
    # re-digesting a day replaces it instead of piling up
    memory.digest(s, conn, FakeBrain(), "2026-09-03")
    assert conn.execute("SELECT count(*) FROM memories WHERE kind = 'digest'").fetchone()[0] == 1


def test_dates_ranking_and_bad_queries(conn):
    _chat(conn, "kubernetes operator idea", day="2026-08-01")
    _chat(conn, "another kubernetes thought", day="2026-09-20")
    assert [h["day"] for h in memory.search(conn, "kubernetes", since="2026-09-01")] == ["2026-09-20"]
    assert memory.search(conn, 'kubernetes" OR (') is not None  # malformed FTS syntax falls back to words
    assert memory.fts_query("try sushi") == '"try"* OR "sushi"*'
    days = memory.timeline(conn)
    assert [d["day"] for d in days] == ["2026-09-20", "2026-08-01"] and days[0]["chats"]


def test_today_is_not_digested_yet(conn):
    _chat(conn, "something today", day=memory.today())
    assert memory.pending_days(conn) == []


def test_markdown_files_are_the_source_of_truth(conn, s):
    _chat(conn, "remember the omakase place, Sushi Ishii, I want to go there")
    memory.digest(s, conn, FakeBrain(), "2026-09-03")
    f = s.home / "memory" / "2026-09-03.md"
    text = f.read_text()
    assert text.startswith("# Thursday 03 September 2026") and "#japanese #food" in text
    # the user fixes a fact by hand: the index follows
    import os
    import time

    f.write_text(text.replace("Sushi Ishii", "Sushi Saito"))
    os.utime(f, (time.time() + 5, time.time() + 5))
    memory.sync_files(s, conn)
    assert "Sushi Saito" in memory.search(conn, "japanese food")[0]["text"]
    # deleting the file forgets the day for good (no re-digest next night)
    f.unlink()
    memory.sync_files(s, conn)
    assert memory.search(conn, "japanese food") == [] and memory.pending_days(conn) == []


def test_markdown_round_trip():
    md = memory.to_markdown(
        "2026-10-03", "Did things.", [{"text": "Likes ramen.", "tags": "japanese food, noodles"}]
    )
    assert memory.from_markdown(md) == (
        "Did things.",
        [{"text": "Likes ramen.", "tags": "japanese food noodles"}],
    )
