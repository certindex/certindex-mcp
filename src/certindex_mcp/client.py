"""HTTP client wrapper for the CertIndex public REST API.

The MCP tool layer in :mod:`certindex_mcp.server` is intentionally a
thin shim — every tool call resolves to a single HTTPS request against
``{base_url}/mcp-api/{tool_name}`` with the caller's API key in the
``X-API-Key`` header.

Keeping all networking in this module makes the package easy to audit:
there is exactly one place that opens sockets, exactly one place that
reads the API key from the environment, and exactly one place that
decides what an error response looks like to the LLM.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.ctindex.io"
DEFAULT_TIMEOUT_SECONDS = 30.0
USER_AGENT = "certindex-mcp/0.2.0 (+https://github.com/certindex/certindex-mcp)"


class CertIndexConfigError(RuntimeError):
    """Raised on missing / malformed configuration (no API key, bad URL)."""


class CertIndexClient:
    """Minimal async HTTP client over the CertIndex ``/mcp-api`` surface."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("CERTINDEX_API_KEY", "")).strip()
        if not self.api_key:
            raise CertIndexConfigError(
                "CERTINDEX_API_KEY is required. Mint a key at https://ctindex.io/app/keys "
                "and set it in your MCP client config (Claude Desktop: the `env` block; "
                "MCP Inspector: shell env)."
            )
        raw_base = (base_url or os.environ.get("CERTINDEX_BASE_URL") or DEFAULT_BASE_URL).strip()
        parsed = httpx.URL(raw_base) if raw_base else None
        if (
            parsed is None
            or parsed.scheme not in ("http", "https")
            or not parsed.host
        ):
            raise CertIndexConfigError(
                f"CERTINDEX_BASE_URL must be a fully-qualified http(s) URL (got: {raw_base!r})"
            )
        # Refuse plaintext HTTP except for an explicit localhost
        # carve-out — the SECURITY.md posture promises HTTPS-only and
        # silently accepting ``http://`` against an arbitrary host
        # would downgrade traffic carrying the API key. Operators
        # running a self-hosted dev instance on the loopback interface
        # are the only legitimate plain-HTTP case.
        if parsed.scheme == "http" and parsed.host not in ("localhost", "127.0.0.1", "::1"):
            raise CertIndexConfigError(
                "CERTINDEX_BASE_URL must use https:// (plaintext http:// "
                "is only allowed against localhost for self-hosted dev)"
            )
        self.base_url = raw_base.rstrip("/")
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.environ.get("CERTINDEX_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "X-API-Key": self.api_key,
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            # No follow_redirects: ``/mcp-api`` never redirects, and an
            # unexpected 30x is more interesting as a hard error than
            # as a silent host change.
            follow_redirects=False,
        )

    async def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """GET ``{base}/mcp-api{path}`` and return the parsed JSON body.

        Non-2xx responses are surfaced as a structured dict the LLM can
        reason about, *not* raised — raising would turn a 422 into an
        opaque transport-level failure in the MCP client.
        """
        # Drop None-valued params so query strings stay tidy and the
        # server doesn't see empty filters as "filter to empty".
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        async with self._client() as client:
            resp = await client.get(f"/mcp-api{path}", params=clean)
        if resp.status_code >= 400:
            return _error_body(resp)
        return resp.json()

    async def get_v1(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """GET ``{base}/v1{path}`` — same error semantics as :meth:`get`.

        Used by the tools whose canonical REST surface lives under
        ``/v1`` rather than the ``/mcp-api`` tool mirror (async sweeps).
        """
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        async with self._client() as client:
            resp = await client.get(f"/v1{path}", params=clean)
        if resp.status_code >= 400:
            return _error_body(resp)
        return resp.json()

    async def post_v1(self, path: str, body: dict | None = None) -> dict[str, Any]:
        """POST ``{base}/v1{path}`` with a JSON body — same error semantics.

        None-valued keys are dropped so the server never sees explicit
        nulls as "filter to empty".
        """
        clean = {k: v for k, v in (body or {}).items() if v is not None}
        async with self._client() as client:
            resp = await client.post(f"/v1{path}", json=clean)
        if resp.status_code >= 400:
            return _error_body(resp)
        return resp.json()


def _error_body(resp: httpx.Response) -> dict[str, Any]:
    """Convert a non-2xx response into a tool-friendly error dict."""
    try:
        body = resp.json()
    except Exception:
        body = {"message": resp.text[:500]}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return {"error": detail.get("error", "http_error"), "status": resp.status_code, **detail}
    return {
        "error": "http_error",
        "status": resp.status_code,
        "message": (detail if isinstance(detail, str) else None) or str(body),
    }
