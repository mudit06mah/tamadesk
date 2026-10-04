"""Runs the assistant: your own `claude -p` with tamadesk's tools, agent-reach's login-free web search
(Exa, from ~/.mcporter/mcporter.json) and WebFetch. Nothing else: no shell, no file edits.

Every run is capped by --max-budget-usd, and asks stop for the day once usage passes the daily cap.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tamadesk.core import db, usage
from tamadesk.core.config import Settings

ALLOWED = ["mcp__tamadesk", "WebFetch"]


class BudgetError(RuntimeError):
    pass


def reach_servers(s: Settings) -> dict:
    """agent-reach's MCP servers (login-free ones only, as allowed in config) in Claude Code's format."""
    path = Path.home() / ".mcporter" / "mcporter.json"
    try:
        servers = json.loads(path.read_text()).get("mcpServers", {})
    except (OSError, ValueError):
        return {}
    return {n: {"type": "http", "url": c["baseUrl"]} for n, c in servers.items()
            if n in s.assistant.reach_servers and c.get("baseUrl")}  # fmt: skip


def mcp_config(s: Settings) -> str:
    tamadesk = {"type": "stdio", "command": sys.executable, "args": ["-m", "tamadesk.assistant.mcp"],
                "env": {"TAMADESK_HOME": str(s.home)}}  # fmt: skip
    return json.dumps({"mcpServers": {"tamadesk": tamadesk, **reach_servers(s)}})


def system_prompt(s: Settings, conn: sqlite3.Connection) -> str:
    about = db.get_profile(conn, "about", {})
    buddy = db.get_profile(conn, "companion") or {"name": "Bolt", "species": "bot"}
    voice = db.get_profile(conn, "voice")
    me = about.get("name") or "the user"
    lines = "\n".join(f"- {k}: {v}" for k, v in about.items() if v)
    return f"""You are {buddy["name"]}, a small pixel {buddy["species"]} who lives on {me}'s desk and is their personal assistant. Now: {datetime.now().astimezone():%A %d %B %Y, %H:%M %Z}.

About {me}:
{lines or "- (nothing yet)"}
{f"Their writing voice: {voice['summary']} Do: {'; '.join(voice['do'])}. Don't: {'; '.join(voice['dont'])}." if voice else ""}

How you work:
- Do the task, don't describe how it could be done. Use tools; ask a question only if you truly can't proceed.
- Be efficient: few tool calls, small limits, stop once you have enough. Prefer the free `search` tool (arXiv, HN, GitHub, RSS, Exa) before reading pages.
- Anything recurring ("keep an eye on", "every morning", "find me X regularly") becomes a tab via create_tab, with precise sources (GitHub qualifiers like topic:x language:y; several narrow queries beat one broad one). Then put the best current results in with add_to_tab so it isn't empty.
- Emails go to Mail as drafts via draft_email, in {me}'s voice, short and specific. Never say an email was sent. Only use addresses published on a page you saw (pass it as email_source); a guessed address must have email_sure=false.
- Todos, reminders and log lines: use the tools, then confirm in one line.
- Reply in short markdown: a sentence or two, then bullets with links if useful. No preamble. Never invent facts about {me} or about things you didn't look up."""


def command(s: Settings, *, prompt: str, system: str, budget: float, resume: str | None = None,
            stream: bool = True, schema: dict | None = None, model: str | None = None) -> list[str]:  # fmt: skip
    cmd = ["claude", "-p", prompt, "--model", model or s.assistant.model, "--effort", s.assistant.effort,
           "--append-system-prompt", system, "--mcp-config", mcp_config(s), "--strict-mcp-config",
           "--tools", "WebFetch", "--allowedTools", ",".join(ALLOWED + [f"mcp__{n}" for n in reach_servers(s)]),
           "--permission-mode", "dontAsk", "--max-budget-usd", f"{budget:.2f}"]  # fmt: skip
    if stream:
        cmd += ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
    else:
        cmd += ["--output-format", "json", "--no-session-persistence"]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def check_budget(s: Settings, conn: sqlite3.Connection) -> None:
    spent = usage.today(conn)["usd"]
    if spent >= s.assistant.daily_usd:
        raise BudgetError(
            f"today's assistant budget (${s.assistant.daily_usd:.2f}) is used up; raise it in Settings"
        )


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in {"ANTHROPIC_API_KEY", "CLAUDE_CODE_SIMPLE"}}


def stream(s: Settings, cmd: list[str]) -> Iterator[dict]:
    """Run claude and translate its stream-json into small UI events:
    {type: session|text|tool|done|error}."""
    proc = subprocess.Popen(cmd, cwd=s.home, env=_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)  # fmt: skip
    try:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init":
                yield {"type": "session", "session_id": ev.get("session_id")}
            elif t == "stream_event":
                d = ev.get("event", {}).get("delta", {})
                if d.get("type") == "text_delta":
                    yield {"type": "text", "text": d["text"]}
            elif t == "assistant":
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use":
                        yield {"type": "tool", "name": b["name"], "input": b.get("input", {})}
            elif t == "result":
                yield {"type": "done", "text": ev.get("result") or "", "error": bool(ev.get("is_error")),
                       "subtype": ev.get("subtype"), "session_id": ev.get("session_id"), "raw": ev}  # fmt: skip
        proc.wait(timeout=10)
        if proc.returncode not in (0, None):
            yield {"type": "error", "text": (proc.stderr.read() or "claude exited with an error")[-400:]}
    finally:
        if proc.poll() is None:
            proc.kill()


def structured(
    s: Settings, conn: sqlite3.Connection, prompt: str, schema: dict, *, kind: str, budget: float
) -> dict:
    """One non-streaming run with tools that returns JSON (used by 'agent' tab sources)."""
    check_budget(s, conn)
    cmd = command(s, prompt=prompt, system=system_prompt(s, conn), budget=budget, stream=False, schema=schema)
    proc = subprocess.run(cmd, cwd=s.home, env=_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=600, check=False)  # fmt: skip
    raw = json.loads(proc.stdout or "{}")
    usage.record(s, kind, raw)
    if raw.get("is_error") or not isinstance(raw.get("structured_output"), dict):
        raise RuntimeError(str(raw.get("result") or proc.stderr)[-300:])
    return raw["structured_output"]
