"""A local model through Ollama's HTTP API (structured outputs via `format: <json schema>`)."""

from __future__ import annotations

import json

from tamadesk.brain import BrainError
from tamadesk.core.config import Settings
from tamadesk.core.net import NetError, get_json


class OllamaBrain:
    """A local Ollama model as a brain: offline and free, JSON output forced by the schema."""

    name = "Ollama"

    def __init__(self, s: Settings):
        self.s = s

    def _post(self, path: str, body: dict | None, timeout: float) -> dict:
        try:
            return get_json(self.s.brain.ollama_url.rstrip("/") + path, body=body, timeout=timeout)
        except NetError as e:
            raise BrainError("unavailable", f"can't reach ollama at {self.s.brain.ollama_url}: {e}") from e

    def check(self) -> tuple[bool, str]:
        try:
            tags = self._post("/api/tags", None, 5)
        except BrainError as e:
            return False, str(e)
        names = [m["name"] for m in tags.get("models", [])]
        if not any(n.split(":")[0] == self.s.brain.model.split(":")[0] for n in names):
            return False, f"model {self.s.brain.model!r} not pulled. Run `ollama pull {self.s.brain.model}`."
        return True, f"Ollama, model {self.s.brain.model}"

    def ask(
        self, prompt: str, schema: dict, *, system: str = "", light: bool = False, kind: str = "brain"
    ) -> dict:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        r = self._post(
            "/api/chat",
            {"model": self.s.brain.model, "messages": messages, "format": schema, "stream": False},
            self.s.brain.timeout_s,
        )
        try:
            out = json.loads(r["message"]["content"])
        except (KeyError, json.JSONDecodeError) as e:
            raise BrainError("schema", f"model did not return JSON: {str(r)[:300]}") from e
        if not isinstance(out, dict):
            raise BrainError("schema", "model returned JSON that is not an object")
        return out
