"""A minimal MCP server (stdio, JSON-RPC 2.0) exposing tamadesk's tools to Claude Code.

Launched by the assistant runner via --mcp-config; no SDK needed for the four methods it uses.
"""

from __future__ import annotations

import json
import sys

from tamadesk.assistant.tools import TOOLS, call
from tamadesk.core.config import load_settings


def handle(s, msg: dict) -> dict | None:
    """Answer one JSON-RPC message from Claude Code: initialize, list tools, or call one. None for notifications."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notifications (e.g. notifications/initialized) get no reply
        return None
    if method == "initialize":
        result = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "tamadesk", "version": "0.3"}}  # fmt: skip
    elif method == "tools/list":
        result = {
            "tools": [{"name": n, "description": d, "inputSchema": sch} for n, (d, sch, _) in TOOLS.items()]
        }
    elif method == "tools/call":
        p = msg["params"]
        try:
            result = {"content": [{"type": "text", "text": call(s, p["name"], p.get("arguments") or {})}]}
        except Exception as e:  # noqa: BLE001 - errors go back to the model, which can retry differently
            result = {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    """Serve tamadesk's tools over stdio (Claude Code starts this as an MCP server)."""
    s = load_settings()
    for line in sys.stdin:
        if line.strip() and (reply := handle(s, json.loads(line))) is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
