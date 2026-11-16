"""Minimal MCP server (stdio, newline-delimited JSON-RPC 2.0). The episode and its answer key stay in
this process; the connected agent only sees the tools."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional, TextIO

from . import __version__
from .env import Env, tool_schemas

PROTOCOL_VERSION = "2025-06-18"


class Server:
    def __init__(self, level: str, seed: int, result_path: Optional[str] = None):
        self.env = Env(level, seed)
        self.result_path = result_path

    def handle(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = msg.get("method")
        mid = msg.get("id")
        if mid is None:  # notification
            return None
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "kyc-desk", "version": __version__},
                      "instructions": self.env.brief()}
        elif method == "tools/list":
            result = {"tools": [{"name": t["name"], "description": t["description"],
                                 "inputSchema": t["input_schema"]} for t in tool_schemas()]}
        elif method == "tools/call":
            params = msg.get("params") or {}
            obs, _, done, info = self.env.step({"tool": params.get("name"), "args": params.get("arguments") or {}})
            if done and self.result_path and info.get("result"):
                with open(self.result_path, "w", encoding="utf-8") as fh:
                    json.dump(info["result"], fh, indent=2)
            if done:
                obs = dict(obs, episode_over=True)
            result = {"content": [{"type": "text", "text": json.dumps(obs)}], "isError": not obs.get("ok", False)}
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(level: str, seed: int, result_path: Optional[str] = None,
          stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    server = Server(level, seed, result_path)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = server.handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
