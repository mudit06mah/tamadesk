"""The Claude brain: every call is capped and checked against the daily budget."""

import json
import subprocess

import pytest

from tamadesk.brain import BrainError
from tamadesk.brain.claude_code import ClaudeCodeBrain
from tamadesk.core import db
from tamadesk.core.config import get_settings


def test_every_call_is_capped_and_stops_past_the_daily_budget(client, monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        out = {"structured_output": {"ok": True}, "total_cost_usd": 0.01}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    s = get_settings()
    brain = ClaudeCodeBrain(s)
    assert brain.ask("hi", {"type": "object"}, light=True) == {"ok": True}
    cmd = seen[-1]
    assert cmd[cmd.index("--max-budget-usd") + 1] == f"{s.brain.light_usd:.2f}"
    assert cmd[cmd.index("--tools") + 1] == ""

    db.connect(s.db_path).execute(
        "INSERT INTO usage (kind, cost_usd) VALUES ('ask', ?)", (s.assistant.daily_usd,)
    )
    with pytest.raises(BrainError) as e:
        brain.ask("hi", {"type": "object"})
    assert e.value.kind == "budget"
    assert len(seen) == 1  # refused before running claude
