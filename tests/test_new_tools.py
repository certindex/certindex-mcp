"""Wiring tests for the four tools added in 0.2.0.

Covers path routing (/v1 vs /mcp-api), body/param shaping (None-dropping),
and structured-error passthrough — mirrors the style of test_client.py.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from certindex_mcp.client import CertIndexClient

BASE = "https://api.ctindex.io"


def _client(monkeypatch) -> CertIndexClient:
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    return CertIndexClient()


@pytest.mark.asyncio
@respx.mock
async def test_post_v1_drops_none_and_hits_sweeps(monkeypatch):
    c = _client(monkeypatch)
    route = respx.post(f"{BASE}/v1/sweeps").mock(
        return_value=httpx.Response(
            202, json={"sweep_id": "abc", "status": "queued"}
        )
    )
    out = await c.post_v1(
        "/sweeps", body={"cn": "acme", "issuer": None, "is_precert": True}
    )
    assert out["sweep_id"] == "abc"
    import json

    sent = json.loads(route.calls.last.request.content)
    assert sent == {"cn": "acme", "is_precert": True}
    assert route.calls.last.request.headers["x-api-key"] == "k"


@pytest.mark.asyncio
@respx.mock
async def test_get_v1_sweep_results_params(monkeypatch):
    c = _client(monkeypatch)
    route = respx.get(f"{BASE}/v1/sweeps/abc").mock(
        return_value=httpx.Response(200, json={"status": "done", "results": []})
    )
    out = await c.get_v1("/sweeps/abc", params={"page": 2, "limit": 100})
    assert out["status"] == "done"
    assert route.calls.last.request.url.params["page"] == "2"


@pytest.mark.asyncio
@respx.mock
async def test_post_v1_structured_error_passthrough(monkeypatch):
    c = _client(monkeypatch)
    respx.post(f"{BASE}/v1/sweeps").mock(
        return_value=httpx.Response(
            403,
            json={
                "detail": {
                    "error": "tier_not_entitled",
                    "message": "global sweeps require a paid plan",
                }
            },
        )
    )
    out = await c.post_v1("/sweeps", body={"cn": "acme"})
    assert out["error"] == "tier_not_entitled"
    assert out["status"] == 403


@pytest.mark.asyncio
@respx.mock
async def test_usage_and_backfill_ride_mcp_api(monkeypatch):
    c = _client(monkeypatch)
    respx.get(f"{BASE}/mcp-api/usage").mock(
        return_value=httpx.Response(200, json={"tier": "free"})
    )
    bf = respx.get(f"{BASE}/mcp-api/historical_backfill_status").mock(
        return_value=httpx.Response(200, json={"entitled": False})
    )
    assert (await c.get("/usage"))["tier"] == "free"
    out = await c.get(
        "/historical_backfill_status", params={"domain": "example.com"}
    )
    assert out == {"entitled": False}
    assert bf.calls.last.request.url.params["domain"] == "example.com"


async def test_server_registers_ten_tools(monkeypatch):
    """The FastMCP server must expose exactly the ten hosted tools."""
    from certindex_mcp.server import _build_server

    c = _client(monkeypatch)
    mcp = _build_server(c)
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
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
        ]
    )
