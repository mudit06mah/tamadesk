"""Runs Claude Code headless (`claude -p`) under the user's own subscription login.

No API key is ever used: we never pass --bare, and ANTHROPIC_API_KEY is stripped from the child
environment so the CLI can't silently switch to API billing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from tamadesk.brain import BrainError
from tamadesk.core.config import Settings


class ClaudeCodeBrain:
    name = "Claude Code"

    def __init__(self, s: Settings):
        self.s = s

    def check(self) -> tuple[bool, str]:
        if not shutil.which("claude"):
            return False, "claude CLI not found. Install Claude Code, then run `claude` once to log in."
        try:
            out = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True,
                                 text=True, timeout=15, check=False)  # fmt: skip
            info = json.loads(out.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            return False, f"could not read Claude Code login: {e}"
        if not info.get("loggedIn"):
            return False, "Claude Code is installed but not logged in. Run `claude` once to log in."
        return True, f"Claude Code, logged in ({info.get('authMethod', 'unknown')})"

    def ask(self, prompt: str, schema: dict, *, system: str = "", light: bool = False) -> dict:
        """`light` = short text (summaries, picking a template): runs on the cheapest model."""
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--model", self.s.brain.light_model if light else self.s.brain.model,
            "--tools", "",  # text in, JSON out: the brain never needs to touch files or the shell
            "--permission-mode", "dontAsk",
            "--no-session-persistence",
        ]  # fmt: skip
        if system:
            cmd += ["--append-system-prompt", system]
        env = {k: v for k, v in os.environ.items() if k not in {"ANTHROPIC_API_KEY", "CLAUDE_CODE_SIMPLE"}}
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.s.home,  # never inside some project, so no stray CLAUDE.md gets loaded
                env=env,
                stdin=subprocess.DEVNULL,  # otherwise the CLI waits 3s for piped input
                capture_output=True,
                text=True,
                timeout=self.s.brain.timeout_s,
                check=False,
            )
        except FileNotFoundError as e:
            raise BrainError("unavailable", "claude CLI not found") from e
        except subprocess.TimeoutExpired as e:
            raise BrainError("timeout", f"claude -p took longer than {self.s.brain.timeout_s}s") from e

        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            tail = (proc.stderr or proc.stdout)[-500:]
            raise BrainError("rate_limit" if "limit" in tail.lower() else "failed", tail) from None
        if raw.get("is_error") or proc.returncode != 0:
            msg = str(raw.get("result") or raw.get("subtype") or proc.stderr)[-500:]
            raise BrainError("rate_limit" if "limit" in msg.lower() else "failed", msg)
        out = raw.get("structured_output")
        if not isinstance(out, dict):
            raise BrainError("schema", f"no structured output: {str(raw.get('result'))[:300]}")
        return out
