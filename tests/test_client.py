"""Client-side wiring tests for :mod:`certindex_mcp.client`."""
from __future__ import annotations

import pytest

from certindex_mcp.client import CertIndexClient, CertIndexConfigError


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("CERTINDEX_API_KEY", raising=False)
    with pytest.raises(CertIndexConfigError):
        CertIndexClient()


def test_explicit_api_key_overrides_env(monkeypatch):
    monkeypatch.setenv("CERTINDEX_API_KEY", "env-key")
    c = CertIndexClient(api_key="explicit-key")
    assert c.api_key == "explicit-key"


def test_base_url_requires_scheme(monkeypatch):
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    with pytest.raises(CertIndexConfigError):
        CertIndexClient(base_url="api.ctindex.io")


def test_base_url_rejects_plain_http_to_remote_host(monkeypatch):
    """SECURITY.md promises HTTPS-only transport. Plain ``http://``
    against an arbitrary host would downgrade traffic carrying the
    API key — only an explicit localhost carve-out is allowed."""
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    with pytest.raises(CertIndexConfigError):
        CertIndexClient(base_url="http://evil.example.com")


def test_base_url_allows_http_to_localhost(monkeypatch):
    """Self-hosted dev on the loopback interface is the only
    legitimate plain-HTTP case."""
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    c = CertIndexClient(base_url="http://localhost:8080")
    assert c.base_url == "http://localhost:8080"
    c2 = CertIndexClient(base_url="http://127.0.0.1:8080")
    assert c2.base_url == "http://127.0.0.1:8080"


def test_explicit_empty_api_key_raises(monkeypatch):
    monkeypatch.delenv("CERTINDEX_API_KEY", raising=False)
    with pytest.raises(CertIndexConfigError):
        CertIndexClient(api_key="   ")


def test_default_base_url(monkeypatch):
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    c = CertIndexClient()
    assert c.base_url == "https://api.ctindex.io"


def test_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    c = CertIndexClient(base_url="https://staging.ctindex.io/")
    assert c.base_url == "https://staging.ctindex.io"


@pytest.mark.asyncio
async def test_get_returns_structured_error_on_4xx(monkeypatch):
    import respx
    from httpx import Response

    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    c = CertIndexClient(base_url="https://example.test")
    with respx.mock(base_url="https://example.test") as router:
        router.get("/mcp-api/search_certificates").mock(
            return_value=Response(
                422,
                json={
                    "detail": {
                        "error": "invalid_parameter",
                        "parameter": "cn",
                        "message": "contains disallowed characters",
                    }
                },
            )
        )
        body = await c.get("/search_certificates", params={"cn": "x%y"})
    assert body["error"] == "invalid_parameter"
    assert body["parameter"] == "cn"
    assert body["status"] == 422


@pytest.mark.asyncio
async def test_search_forwards_wildcard_san_verbatim(monkeypatch):
    """End-to-end parity guard: a wildcard SAN must be forwarded to
    ``/mcp-api/search_certificates`` as ``*.example.com``, not the
    apex. Exercises the full server tool path including validation +
    request building."""
    import respx
    from httpx import Response

    from certindex_mcp.client import CertIndexClient
    from certindex_mcp.server import _build_server

    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    client = CertIndexClient(base_url="https://example.test")
    server = _build_server(client)
    # FastMCP stores registered tools on the underlying tool manager;
    # call ours directly to bypass MCP transport.
    tool = server._tool_manager._tools["search_certificates"]
    with respx.mock(base_url="https://example.test") as router:
        route = router.get("/mcp-api/search_certificates").mock(
            return_value=Response(
                200, json={"results": [], "has_more": False, "page": 1, "limit": 10}
            )
        )
        await tool.fn(san="*.example.com")
    qs = str(route.calls.last.request.url)
    # URL-encoded; ``*`` may or may not be encoded depending on httpx,
    # so accept either form.
    assert "san=%2A.example.com" in qs or "san=*.example.com" in qs


@pytest.mark.asyncio
async def test_get_drops_none_params(monkeypatch):
    import respx
    from httpx import Response

    monkeypatch.setenv("CERTINDEX_API_KEY", "k")
    c = CertIndexClient(base_url="https://example.test")
    with respx.mock(base_url="https://example.test") as router:
        route = router.get("/mcp-api/search_certificates").mock(
            return_value=Response(200, json={"results": []})
        )
        await c.get(
            "/search_certificates",
            params={"domain": "example.com", "cn": None, "issuer": None},
        )
    # URL should contain ``domain`` but not the dropped Nones.
    qs = str(route.calls.last.request.url)
    assert "domain=example.com" in qs
    assert "cn=" not in qs
    assert "issuer=" not in qs
