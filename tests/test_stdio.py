"""Exercise the installed console script, JSON-RPC framing and HTTP boundary.

No SDK client internals, production credentials or external network are used.
This catches import/startup failures missed by HTTP-wrapper-only tests.
"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

TOOLS = {
    "search_certificates",
    "get_certificate",
    "get_domain_certificates",
    "get_subdomains",
    "get_latest_cert",
    "get_expiring_certs",
    "submit_global_sweep",
    "get_sweep_results",
    "get_usage",
    "get_historical_backfill_status",
}


@pytest.fixture
def upstream():
    state = {"status": 200, "payload": {"tier": "free"}, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            state["requests"].append({
                "method": self.command,
                "path": url.path,
                "query": parse_qs(url.query, keep_blank_values=True),
                "body": json.loads(self.rfile.read(length)) if length else None,
                "api_key": self.headers.get("X-API-Key"),
            })
            body = json.dumps(state["payload"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@asynccontextmanager
async def stdio_client(upstream):
    # Use the console script belonging to THIS interpreter/clean wheel venv.
    executable = Path(sys.executable).parent / "certindex-mcp"
    env = {
        **os.environ,
        "CERTINDEX_API_KEY": "stdio-test-only",
        "CERTINDEX_BASE_URL": upstream["url"],
        "CERTINDEX_TIMEOUT": "2",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    env.pop("PYTHONPATH", None)
    proc = await asyncio.create_subprocess_exec(
        str(executable), env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr = asyncio.create_task(proc.stderr.read())
    next_id = 0

    async def rpc(method, params=None, *, notification=False):
        nonlocal next_id
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            next_id += 1
            message["id"] = next_id
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        await proc.stdin.drain()
        if notification:
            return None
        async with asyncio.timeout(15):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    detail = (await stderr).decode(errors="replace")
                    raise AssertionError(f"Server exited before {method}: {detail}")
                reply = json.loads(line)
                assert reply["jsonrpc"] == "2.0"
                if "id" not in reply:
                    continue
                assert reply["id"] == next_id, reply
                assert "error" not in reply, reply
                return reply["result"]

    try:
        initialized = await rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "certindex-regression", "version": "1"},
        })
        assert initialized["serverInfo"]["name"] == "certindex"
        assert "tools" in initialized["capabilities"]
        await rpc("notifications/initialized", notification=True)
        yield rpc, initialized
    finally:
        if proc.returncode is None:
            proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        await stderr


def tool_json(result):
    assert not result.get("isError", False), result
    text = [block["text"] for block in result["content"] if block["type"] == "text"]
    assert len(text) == 1, result
    return json.loads(text[0])


async def test_installed_console_script_stdio(upstream):
    async with stdio_client(upstream) as (rpc, _initialized):
        listing = await rpc("tools/list")
        assert len(listing["tools"]) == 10
        assert {tool["name"] for tool in listing["tools"]} == TOOLS
        assert all(tool["inputSchema"]["type"] == "object" for tool in listing["tools"])

        usage = tool_json(await rpc("tools/call", {"name": "get_usage", "arguments": {}}))
        assert usage == {"tier": "free"}
        assert upstream["requests"] == [{
            "method": "GET", "path": "/mcp-api/usage", "query": {}, "body": None,
            "api_key": "stdio-test-only",
        }]

        invalid = tool_json(await rpc("tools/call", {
            "name": "get_certificate", "arguments": {"sha256": "not-a-sha"},
        }))
        assert invalid["error"] == "invalid_parameter"
        assert len(upstream["requests"]) == 1

        upstream["status"] = 403
        upstream["payload"] = {"detail": {
            "error": "invalid_api_key", "message": "Test key rejected",
        }}
        denied = tool_json(await rpc("tools/call", {"name": "get_usage", "arguments": {}}))
        assert denied == {
            "error": "invalid_api_key", "message": "Test key rejected", "status": 403,
        }
