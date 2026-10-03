"""The brain: whatever model the user brings. Every call is `ask(prompt, schema) -> dict`.

- claude_code (default): the user's own `claude` CLI, logged in with their own subscription.
  tamadesk never sees a token; it just runs the official binary on the user's machine.
- ollama: a local model, fully offline.
"""

from __future__ import annotations

from typing import Protocol

from tamadesk.core.config import Settings


class BrainError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(f"[{kind}] {message}")
        self.kind = kind  # unavailable | rate_limit | timeout | schema | failed


class Brain(Protocol):
    name: str

    def ask(self, prompt: str, schema: dict, *, system: str = "", light: bool = False) -> dict: ...

    def check(self) -> tuple[bool, str]: ...


def get_brain(s: Settings) -> Brain:
    if s.brain.kind == "ollama":
        from tamadesk.brain.ollama import OllamaBrain

        return OllamaBrain(s)
    from tamadesk.brain.claude_code import ClaudeCodeBrain

    return ClaudeCodeBrain(s)
