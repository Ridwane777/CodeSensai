"""
Tools of an external MCP server, callable by the agent — feature [T1]
(ADR-0041).

MCP (Model Context Protocol): a server exposes tools; we talk to it in
JSON-RPC 2.0, one JSON message per line, over its standard input and output
("stdio" transport). The client fits in four messages: `initialize`, the
`notifications/initialized` notification, `tools/list` and `tools/call`. No
library: the official SDK is asynchronous and pulls in about ten dependencies
for what these few lines do.

Each server tool becomes an agent tool (`mcp_<server>_<tool>`), registered at
startup from `config.json`. It goes through the gateway like the others
(ADR-0006): confirmation according to its risk (`execute` by default,
configurable per server), guardrails on its answer. A server that does not
start, does not answer or crashes is reported, never propagated as an
exception: the agent carries on with the other tools.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from sensai.core.tools import ToolResult
from sensai.execution.tool_policy import Risk

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT_S = 30.0
MAX_TOOL_NAME = 64
_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_KEYS = {"command", "args", "env", "cwd", "risk", "timeout_s"}


class McpError(Exception):
    """The server did not answer, answered with an error, or is gone."""


def parse_mcp_config(raw: Any) -> dict[str, dict[str, Any]]:
    """The `mcp_servers` section of config.json, validated. An error stops
    startup: a badly described server must not pass for a connected one."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("mcp_servers must be an object {name: {command, args…}}")
    servers = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not _SERVER_NAME.match(name):
            raise ValueError(
                f"mcp_servers: invalid server name {name!r} (letters, digits, _ and -)"
            )
        if not isinstance(spec, dict):
            raise ValueError(f"mcp_servers.{name} must be an object")
        unknown = set(spec) - _KEYS
        if unknown:
            raise ValueError(f"mcp_servers.{name}: unknown key {sorted(unknown)}")
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"mcp_servers.{name}: missing command")
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"mcp_servers.{name}: args must be a list of strings")
        env = spec.get("env", {})
        if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
            raise ValueError(f"mcp_servers.{name}: env must map names to strings")
        risk = spec.get("risk", Risk.EXECUTE.value)
        if risk not in {r.value for r in Risk}:
            raise ValueError(
                f"mcp_servers.{name}: risk must be read, network, write or execute"
            )
        timeout = spec.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"mcp_servers.{name}: timeout_s must be a positive number")
        servers[name] = {"command": command, "args": args, "env": env, "cwd": spec.get("cwd"),
                         "risk": risk, "timeout_s": float(timeout)}
    return servers


class McpServer:
    """An MCP server started as a subprocess, queried line by line."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name, self.timeout = name, spec["timeout_s"]
        self._next_id = 0
        self._lock = threading.Lock()  # one request at a time: replies in order
        self._replies: queue.Queue[dict | None] = queue.Queue()
        # The server inherits the environment (PATH…) plus what the config adds.
        env = {**os.environ, **spec["env"]}
        self._proc = subprocess.Popen(
            [spec["command"], *spec["args"]], cwd=spec["cwd"], env=env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1,
        )
        threading.Thread(target=self._read, daemon=True, name=f"mcp-{name}").start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                log.warning("MCP %s: unreadable line ignored", self.name)
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                self._answer_server_request(message)
            elif "id" in message:
                self._replies.put(message)
        self._replies.put(None)  # output closed: the server stopped

    def _answer_server_request(self, message: dict) -> None:
        """The server may query us (ping) or notify us (logs)."""
        if "id" not in message:
            return  # notification: nothing to answer
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        if message.get("method") == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": "method not supported"}
        self._write(reply)

    def _write(self, message: dict) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._next_id += 1
            mid = self._next_id
            try:
                self._write({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
            except (BrokenPipeError, OSError, ValueError) as e:
                raise McpError(f"MCP server \"{self.name}\" stopped") from e
            while True:
                try:
                    reply = self._replies.get(timeout=self.timeout)
                except queue.Empty:
                    raise McpError(
                        f"MCP server \"{self.name}\" did not answer after {self.timeout:g} s"
                    ) from None
                if reply is None:
                    self._replies.put(None)  # later calls will see it too
                    raise McpError(f"MCP server \"{self.name}\" stopped")
                if reply.get("id") == mid:
                    break  # a late reply to an abandoned call is ignored
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise McpError(f"MCP server \"{self.name}\": {error.get('message', 'error')}")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise McpError(f"MCP server \"{self.name}\": reply without a result")
        return result

    def start(self) -> list[dict]:
        """MCP handshake, then the list of its tools (all pages)."""
        self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                    "clientInfo": {"name": "codesensei", "version": "0.1"}})
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools, cursor = [], None
        while True:
            page = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += [t for t in page.get("tools", []) if isinstance(t, dict) and t.get("name")]
            cursor = page.get("nextCursor")
            if not cursor:
                return tools

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()


class McpTool:
    """A tool of an MCP server, seen by the agent like any other tool."""

    def __init__(self, server: McpServer, spec: dict[str, Any], risk: str) -> None:
        self.server, self.remote_name = server, str(spec["name"])
        self.name = f"mcp_{server.name}_{_UNSAFE.sub('_', self.remote_name)}"[:MAX_TOOL_NAME]
        self.description = f"[MCP {server.name}] {spec.get('description') or self.remote_name}"
        schema = spec.get("inputSchema")
        self.parameters = (schema if isinstance(schema, dict) and schema.get("type") == "object"
                           else {"type": "object", "properties": {}})
        self.risk = risk
        self.timeout_s = server.timeout + 5  # the gateway lets the client finish

    def describe_call(self, **args: Any) -> str:
        """What the user approves: which server, which tool, which arguments."""
        shown = json.dumps(args, ensure_ascii=False)
        shown = shown if len(shown) <= 300 else shown[:299] + "…"
        return f"Tool \"{self.remote_name}\" of MCP server \"{self.server.name}\": {shown}"

    def run(self, **kwargs) -> ToolResult:
        try:
            result = self.server.request(
                "tools/call", {"name": self.remote_name, "arguments": kwargs}
            )
        except McpError as e:
            return ToolResult(ok=False, content=str(e))
        texts = [str(item.get("text", "")) for item in result.get("content", [])
                 if isinstance(item, dict) and item.get("type") == "text"]
        structured = result.get("structuredContent", {})
        content = "\n".join(texts) or json.dumps(structured, ensure_ascii=False)
        return ToolResult(ok=not result.get("isError", False), content=content)


def load_mcp_tools(
    servers: dict[str, dict[str, Any]],
) -> tuple[list[McpTool], list[str], Callable[[], None]]:
    """Starts each server and returns (tools, warnings, close function).
    A failing server yields a warning; the others stay connected."""
    tools: list[McpTool] = []
    warnings: list[str] = []
    running: list[McpServer] = []
    for name, spec in servers.items():
        try:
            server = McpServer(name, spec)
        except OSError as e:
            warnings.append(f"MCP server \"{name}\" could not be started: {e}")
            continue
        try:
            remote = server.start()
        except McpError as e:
            warnings.append(f"MCP server \"{name}\" skipped: {e}")
            server.close()
            continue
        running.append(server)
        tools += [McpTool(server, spec_, spec["risk"]) for spec_ in remote]

    def close() -> None:
        for server in running:
            server.close()

    return tools, warnings, close
