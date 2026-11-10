"""Fake MCP server (stdio, line-by-line JSON-RPC) for tests/tools/test_mcp_tool.py.

    python fake_mcp_server.py [normal|crash|silent|garbage]
"""
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
TOOLS = [
    {"name": "add", "description": "Adds two numbers.",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "leak", "description": "Returns a secret.", "inputSchema": {"type": "object"}},
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object"}},
    {"name": "bad name!", "description": "Name to sanitize."},
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue  # notification
    if MODE == "silent":
        continue
    if MODE == "garbage":
        sys.stdout.write("this is not JSON\n")
        sys.stdout.flush()
        continue
    method, mid = msg.get("method"), msg["id"]
    print(f"log: {method}", file=sys.stderr, flush=True)  # a real server logs to stderr
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        # a server notification in the middle: the client must ignore it
        send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}})
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments", {})
        if MODE == "crash":
            sys.exit(3)
        if name == "add":
            result = {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}
        elif name == "leak":
            secret = 'API_KEY = "sk-abcdef1234567890abcdef"'
            result = {"content": [{"type": "text", "text": secret}]}
        else:
            result = {"content": [{"type": "text", "text": "server-side failure"}], "isError": True}
        send({"jsonrpc": "2.0", "id": mid, "result": result})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown"}})
