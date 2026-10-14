"""News tabs that stay on topic: a news source that links to the publisher, Hacker News topics that need
every word, match words that drop off-topic items, and tabs checked for relevance when they hatch.
All made up (example.com), no network."""

from tamadesk.assistant import tools
from tamadesk.modules import engine, sources, spec
from tamadesk.modules.sources import Item

RSS = """<rss xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss"><channel><item>
<title>Satellite internet gets a licence in a new market</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fnews.example.com%2fstory-1&amp;c=1</link>
<description>Regulators approved the service on Friday.</description>
<pubDate>Sun, 11 Oct 2026 00:57:36 GMT</pubDate>
<News:Source>Example Times on MSN</News:Source>
<News:Image>http://www.bing.com/th?id=OVFT.example&amp;pid=News</News:Image>
</item></channel></rss>"""


def test_news_links_to_the_publisher(monkeypatch):
    asked = {}

    def get_text(url, params=None, **kw):
        asked.update(params)
        return RSS

    monkeypatch.setattr(sources, "get_text", get_text)
    [it] = sources.news("satellite internet", market="en-in")
    assert asked == {"q": "satellite internet", "format": "rss", "mkt": "en-in"}
    assert it.url == "https://news.example.com/story-1"  # not Bing's click-through
    assert (it.subtitle, it.published) == ("Example Times", "2026-10-11T00:57:36+00:00")
    assert it.body == "Regulators approved the service on Friday." and it.data["thumb"].startswith(
        "http://www.bing.com/th"
    )


def test_hn_topics_need_every_word(monkeypatch):
    calls = []

    def get_json(url, params=None, **kw):
        calls.append(params)
        return {"hits": [{"objectID": "1", "title": "Same story", "url": "https://example.com/1"}]}

    monkeypatch.setattr(sources, "get_json", get_json)
    got = sources.hn("satellite internet india, rocket reuse", min_points=0)
    assert [c["query"] for c in calls] == ["satellite internet india", "rocket reuse"]  # one search per topic
    assert all("optionalWords" not in c and c["typoTolerance"] == "false" for c in calls)
    assert len(got) == 1  # the same story from both searches shows once


def test_match_words_drop_what_is_off_topic(conn, monkeypatch):
    found = [Item(ext_id="1", title="Rocket company lands its booster", url="https://example.com/1"),
             Item(ext_id="2", title="A barbershop playlist", url="https://example.com/2"),
             Item(ext_id="3", title="Muskrats return to the river", url="https://example.com/3")]  # fmt: skip
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: found)
    m = spec.Module(id="space", name="Space", sources=[{"type": "fake"}], match=["rocket", "musk"])
    r = engine.run(conn, m)
    assert (r["added"], r["left_out"]) == (1, {"off topic": 2})  # 'musk' is a word, not part of 'muskrat'
    engine.rescore(
        conn, m.model_copy(update={"match": ["satellite"]})
    )  # a narrower topic clears what's off it
    assert conn.execute("SELECT count(*) FROM items WHERE status = 'new'").fetchone()[0] == 0


def test_a_new_tab_is_checked_for_relevance_not_just_results(client, monkeypatch):
    noise = [
        Item(ext_id=str(i), title=f"Unrelated story {i}", url=f"https://example.com/{i}") for i in range(9)
    ]
    monkeypatch.setitem(sources.SOURCES, "fake", lambda **kw: noise + [Item(ext_id="x", title="Rocket news")])
    m = spec.Module(id="space", name="Space", sources=[{"type": "fake"}], match=["rocket"])
    [problem] = tools._broken(m)
    assert "mostly off topic: 1 of 10 mention rocket" in problem


def test_the_follow_a_story_template():
    m = spec.from_template("story", {"query": "rocket reuse", "names": "rocket, booster"})
    assert m.match == ["rocket", "booster"] and m.sources[0].model_dump() == {
        "type": "news",
        "query": "rocket reuse",
    }
