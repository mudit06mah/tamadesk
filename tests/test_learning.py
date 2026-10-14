"""Learning paths and videos: a roadmap tab finds the best few videos per topic in order, video cards say
what a video is (not the channel's promo), and tabs show what they learned from bookmarks. No network."""

import json

from tamadesk.assistant import tools
from tamadesk.core.config import get_settings
from tamadesk.modules import engine, rank, sources, spec, youtube

PROMO = """What's actually happening to a neural network as it learns?
Help fund future projects: https://www.patreon.com/example
0:00 Introduction
Enrollment link: example.in/bootcamp
An equally valuable form of support is to share the videos. #deeplearning"""


def video(i: str, title: str, duration: int = 600, views: int = 10_000, description: str = "") -> dict:
    return {"id": i.ljust(11, "x"), "title": title, "channel": "Example Channel", "duration": duration,
            "views": views, "description": description}  # fmt: skip


def test_a_description_says_what_the_video_is():
    assert youtube.blurb(PROMO) == "What's actually happening to a neural network as it learns?"
    assert youtube.blurb("") == ""
    assert youtube.blurb("Ready to start your career in AI? Signals that a model is overfitting.") == (
        "Signals that a model is overfitting."
    )
    assert (
        youtube.blurb("The book is back in stock! Example Posters:\nHow a perceptron learns.")
        == "How a perceptron learns."
    )


def test_picks_are_on_topic_explainers_not_shorts():
    found = [video("a", "Backpropagation in 60 seconds #shorts", duration=55, views=9_000_000),
             video("b", "My week as an ML engineer", views=2_000_000),
             video("c", "Backpropagation, intuitively", views=500_000),
             video("d", "Backpropagation calculus", views=300_000)]  # fmt: skip
    assert [v["title"] for v in youtube.pick(found, "backpropagation", 2)] == [
        "Backpropagation, intuitively",
        "Backpropagation calculus",
    ]


def test_a_roadmap_is_topics_in_order_with_their_videos(monkeypatch):
    asked = []

    def search(q, n):
        asked.append(q)
        topic = q.split(" neural")[0]
        return [video(topic[:4] + "1", f"{topic} explained", description="A short tour of the idea."),
                video(topic[:4] + "2", f"{topic} from scratch")]  # fmt: skip

    monkeypatch.setattr(youtube, "search", search)
    monkeypatch.setattr(youtube, "details", lambda url: {"description": "Built line by line in Python."})
    got = sources.roadmap("neural networks", "1. Perceptrons\n2. Backpropagation", per_topic=2)
    assert asked == ["Perceptrons neural networks", "Backpropagation neural networks"]
    assert [(i.data["step"], i.data["topic"]) for i in got] == [(1, "Perceptrons")] * 2 + [
        (2, "Backpropagation")
    ] * 2
    assert got[0].body == "A short tour of the idea." and got[1].body == "Built line by line in Python."
    assert got[0].data["thumb"].startswith("https://i.ytimg.com/vi/") and got[0].url.startswith(
        "https://www.youtube.com/watch"
    )


def test_a_steps_tab_keeps_its_order_and_what_you_watched(client, conn, monkeypatch):
    path = [sources.Item(ext_id=f"v{i}", title=f"video {i}", url=f"https://example.com/{i}", data={"step": s, "topic": t})
            for i, (s, t) in enumerate([(2, "backprop"), (1, "perceptrons"), (2, "backprop")])]  # fmt: skip
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: path)
    m = spec.Module(
        id="nn", name="NN", layout="steps", sources=[{"type": "fake"}], actions=["done", "skip", "open"]
    )
    assert m.expire_days == 365  # a path isn't news: nothing in it expires
    t = spec.from_template("roadmap", {"subject": "ml", "topics": "perceptrons\ngradient descent"})
    assert (
        t.sources[0].model_dump()["topics"] == "perceptrons\ngradient descent"
    )  # one topic per line survives
    engine.run(conn, m)
    ids = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM items")}
    engine.act(conn, ids["video 1"], "done")
    engine.act(conn, ids["video 2"], "skip")
    got = client.get("/api/modules/nn/items?status=path").json()["items"]
    assert [(i["title"], i["data"]["step"], i["status"]) for i in got] == [
        ("video 1", 1, "done"),
        ("video 0", 2, "new"),
    ]


def test_a_channel_feed_shows_the_video_not_the_promo():
    xml = f"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/"><entry>
      <id>yt:video:abc</id><title>Backpropagation, intuitively</title>
      <link rel="alternate" href="https://www.youtube.com/watch?v=Ilg3gGewQ5U"/>
      <published>2026-09-01T10:00:00+00:00</published>
      <media:group><media:description>{PROMO}</media:description>
        <media:community><media:statistics views="6313661"/></media:community></media:group></entry></feed>"""
    [it] = sources.parse_feed(xml)
    assert it.body == "What's actually happening to a neural network as it learns?"
    assert it.data == {"views": 6313661} and it.published.startswith("2026-09-01")
    assert it.subtitle == "6.3M views"  # (this made-up feed names no channel)


def test_videos_bolt_adds_get_their_details_once(client, conn, monkeypatch):
    calls = []

    def details(url):
        calls.append(url)
        return {"channel": "Example Channel", "duration": 0, "views": 0, "description": "Neural networks from the ground up.",
                "thumb": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg", "videos": 12}  # fmt: skip

    monkeypatch.setattr(youtube, "details", details)
    m = spec.Module(id="learn", name="Learn", sources=[{"type": "rss", "url": "https://example.com/feed"}])
    spec.save(get_settings(), m)
    tools.add_to_tab(get_settings(), conn, "learn", [{"title": "Neural nets series", "subtitle": "Best visual intuition",
                     "url": "https://www.youtube.com/playlist?list=PLexample"}])  # fmt: skip
    row = conn.execute("SELECT subtitle, body, data FROM items").fetchone()
    assert row["subtitle"] == "Example Channel · playlist of 12 videos"
    assert (
        row["body"] == "Best visual intuition. Neural networks from the ground up."
    )  # Bolt's note stays first
    assert json.loads(row["data"])["thumb"].endswith("mqdefault.jpg")
    youtube.fill(conn, "learn")
    assert len(calls) == 1  # tried once


def test_a_tab_says_what_it_learned_from_bookmarks_and_passes(client, conn):
    for _ in range(2):
        rank.learn(conn, "news", "rust compilers release", liked=True)
        rank.learn(conn, "news", "crypto token launch", liked=False)
    got = rank.taste(conn, "news")
    assert set(got["more"]) == {"rust", "compilers", "release"} and set(got["less"]) == {
        "crypto",
        "token",
        "launch",
    }
