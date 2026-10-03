"""A local model through Ollama's HTTP API (structured outputs via `format: <json schema>`)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from tamadesk.brain import BrainError
from tamadesk.core.config import Settings


class OllamaBrain:
    name = "Ollama"

    def __init__(self, s: Settings):
        self.s = s

    def _post(self, path: str, body: dict | None, timeout: float) -> dict:
        req = urllib.request.Request(
            self.s.brain.ollama_url.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except TimeoutError as e:
            raise BrainError("timeout", f"ollama took longer than {timeout:.0f}s") from e
        except (urllib.error.URLError, OSError) as e:
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

    def ask(self, prompt: str, schema: dict, *, system: str = "") -> dict:
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
