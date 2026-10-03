from datetime import UTC, datetime

from tamadesk.life.capture import parse

NOW = datetime(2026, 10, 3, 14, 0)  # a Saturday afternoon, local time


def test_plain_text_is_a_log_entry():
    c = parse("finally fixed the flaky test, went for a run", NOW)
    assert c.kind == "log"
    assert c.due_at is None


def test_todo_prefixes():
    for text in [
        "todo send the invoice",
        "TODO: send the invoice",
        "[] send the invoice",
        "- [ ] send the invoice",
    ]:
        c = parse(text, NOW)
        assert (c.kind, c.text) == ("todo", "send the invoice"), text


def test_reminder_with_clock_time():
    c = parse("remind me to call mom at 6pm", NOW)
    assert c.kind == "reminder"
    assert c.text == "call mom"
    assert c.due_at == datetime(2026, 10, 3, 18, 0).astimezone(UTC).replace(tzinfo=None)


def test_reminder_relative():
    c = parse("remind me in 20 minutes to stretch", NOW)
    assert c.kind == "reminder"
    assert c.text == "stretch"
    expected = datetime(2026, 10, 3, 14, 20).astimezone(UTC).replace(tzinfo=None)
    assert c.due_at == expected


def test_reminder_without_time_becomes_todo():
    c = parse("remind me to water the plants", NOW)
    assert (c.kind, c.text) == ("todo", "water the plants")


def test_words_that_look_like_dates_are_ignored():
    c = parse("remind me to ask may about a sec", NOW)
    assert c.kind == "todo"
