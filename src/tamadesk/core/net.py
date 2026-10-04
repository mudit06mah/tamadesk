"""One small HTTP helper for everything that talks to the network (sources, Ollama). Stdlib only."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "tamadesk/0.2 (+https://github.com/mudit06mah/tamadesk)"}


class NetError(RuntimeError):
    pass


def fetch(url: str, *, params: dict | None = None, body: dict | None = None, timeout: float = 20,
          headers: dict | None = None, method: str | None = None) -> bytes:  # fmt: skip
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers=UA | {"Content-Type": "application/json"} | (headers or {}),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise NetError(f"{urllib.parse.urlsplit(url).netloc}: {e}") from e


def get_json(url: str, **kw):
    return json.loads(fetch(url, **kw))


def get_text(url: str, **kw) -> str:
    return fetch(url, **kw).decode("utf-8", "replace")
