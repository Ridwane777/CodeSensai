"""
Outils d'un serveur MCP externe, appelables par l'agent — feature [T1]
(ADR-0041).

MCP (Model Context Protocol) : un serveur expose des outils ; on lui parle en
JSON-RPC 2.0, un message JSON par ligne, sur son entrée et sa sortie standard
(transport « stdio »). Le client tient en quatre messages : `initialize`, la
notification `notifications/initialized`, `tools/list` et `tools/call`. Pas de
bibliothèque : le SDK officiel est asynchrone et tire une dizaine de
dépendances pour ce que ces quelques lignes font.

Chaque outil du serveur devient un outil de l'agent (`mcp_<serveur>_<outil>`),
enregistré au démarrage d'après `config.json`. Il passe par la passerelle
comme les autres (ADR-0006) : confirmation selon son risque (`execute` par
défaut, réglable par serveur), garde-fous sur sa réponse. Un serveur qui ne
démarre pas, ne répond pas ou plante est signalé, jamais propagé en exception :
l'agent continue avec les autres outils.
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
    """Le serveur n'a pas répondu, a répondu une erreur ou n'est plus là."""


def parse_mcp_config(raw: Any) -> dict[str, dict[str, Any]]:
    """La section `mcp_servers` de config.json, vérifiée. Une erreur arrête le
    démarrage : un serveur mal décrit ne doit pas passer pour branché."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("mcp_servers doit être un objet {nom: {command, args…}}")
    servers = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not _SERVER_NAME.match(name):
            raise ValueError(
                f"mcp_servers : nom de serveur invalide {name!r} (lettres, chiffres, _ et -)"
            )
        if not isinstance(spec, dict):
            raise ValueError(f"mcp_servers.{name} doit être un objet")
        unknown = set(spec) - _KEYS
        if unknown:
            raise ValueError(f"mcp_servers.{name} : clé inconnue {sorted(unknown)}")
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"mcp_servers.{name} : command manquant")
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"mcp_servers.{name} : args doit être une liste de chaînes")
        env = spec.get("env", {})
        if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
            raise ValueError(f"mcp_servers.{name} : env doit associer des noms à des chaînes")
        risk = spec.get("risk", Risk.EXECUTE.value)
        if risk not in {r.value for r in Risk}:
            raise ValueError(
                f"mcp_servers.{name} : risk doit valoir read, network, write ou execute"
            )
        timeout = spec.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"mcp_servers.{name} : timeout_s doit être un nombre positif")
        servers[name] = {"command": command, "args": args, "env": env, "cwd": spec.get("cwd"),
                         "risk": risk, "timeout_s": float(timeout)}
    return servers


class McpServer:
    """Un serveur MCP lancé en sous-processus, interrogé ligne à ligne."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name, self.timeout = name, spec["timeout_s"]
        self._next_id = 0
        self._lock = threading.Lock()  # une requête à la fois : réponses dans l'ordre
        self._replies: queue.Queue[dict | None] = queue.Queue()
        # Le serveur hérite de l'environnement (PATH…) plus ce que la config ajoute.
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
                log.warning("MCP %s : ligne illisible ignorée", self.name)
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                self._answer_server_request(message)
            elif "id" in message:
                self._replies.put(message)
        self._replies.put(None)  # sortie fermée : le serveur s'est arrêté

    def _answer_server_request(self, message: dict) -> None:
        """Le serveur peut nous interroger (ping) ou nous notifier (journaux)."""
        if "id" not in message:
            return  # notification : rien à répondre
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        if message.get("method") == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": "méthode non prise en charge"}
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
                raise McpError(f"serveur MCP « {self.name} » arrêté") from e
            while True:
                try:
                    reply = self._replies.get(timeout=self.timeout)
                except queue.Empty:
                    raise McpError(
                        f"serveur MCP « {self.name} » sans réponse après {self.timeout:g} s"
                    ) from None
                if reply is None:
                    self._replies.put(None)  # les appels suivants le verront aussi
                    raise McpError(f"serveur MCP « {self.name} » arrêté")
                if reply.get("id") == mid:
                    break  # une réponse en retard d'un appel abandonné est ignorée
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise McpError(f"serveur MCP « {self.name} » : {error.get('message', 'erreur')}")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise McpError(f"serveur MCP « {self.name} » : réponse sans résultat")
        return result

    def start(self) -> list[dict]:
        """Poignée de main MCP, puis la liste de ses outils (toutes les pages)."""
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
    """Un outil d'un serveur MCP, vu par l'agent comme n'importe quel outil."""

    def __init__(self, server: McpServer, spec: dict[str, Any], risk: str) -> None:
        self.server, self.remote_name = server, str(spec["name"])
        self.name = f"mcp_{server.name}_{_UNSAFE.sub('_', self.remote_name)}"[:MAX_TOOL_NAME]
        self.description = f"[MCP {server.name}] {spec.get('description') or self.remote_name}"
        schema = spec.get("inputSchema")
        self.parameters = (schema if isinstance(schema, dict) and schema.get("type") == "object"
                           else {"type": "object", "properties": {}})
        self.risk = risk
        self.timeout_s = server.timeout + 5  # la passerelle laisse le client conclure

    def describe_call(self, **args: Any) -> str:
        """Ce que l'utilisateur approuve : quel serveur, quel outil, quels arguments."""
        shown = json.dumps(args, ensure_ascii=False)
        shown = shown if len(shown) <= 300 else shown[:299] + "…"
        return f"Outil « {self.remote_name} » du serveur MCP « {self.server.name} » : {shown}"

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
    """Démarre chaque serveur et renvoie (outils, avertissements, fermeture).
    Un serveur en échec donne un avertissement ; les autres restent branchés."""
    tools: list[McpTool] = []
    warnings: list[str] = []
    running: list[McpServer] = []
    for name, spec in servers.items():
        try:
            server = McpServer(name, spec)
        except OSError as e:
            warnings.append(f"serveur MCP « {name} » impossible à lancer : {e}")
            continue
        try:
            remote = server.start()
        except McpError as e:
            warnings.append(f"serveur MCP « {name} » ignoré : {e}")
            server.close()
            continue
        running.append(server)
        tools += [McpTool(server, spec_, spec["risk"]) for spec_ in remote]

    def close() -> None:
        for server in running:
            server.close()

    return tools, warnings, close
