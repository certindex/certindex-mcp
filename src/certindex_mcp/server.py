"""FastMCP stdio entry point for certindex-mcp.

Six tools that mirror the hosted CertIndex MCP surface
(``https://api.ctindex.io/mcp``). Each tool:

  1. Validates input client-side (rejects malformed hostnames /
     SHA-256s / overlong substrings before going to the wire).
  2. Forwards to ``GET /mcp-api/<tool>`` on the configured base URL.
  3. Returns the upstream JSON body verbatim, or a structured error
     dict on validation failure / HTTP error.

The entry point :func:`main` runs the server over stdio so any MCP
client (Claude Desktop, Continue, MCP Inspector, …) can spawn it.

NB: this module deliberately does NOT use ``from __future__ import
annotations``. FastMCP introspects each tool's parameter annotations
at registration time (``issubclass(param.annotation, Context)``); with
PEP 563 deferred evaluation those annotations are strings and the
introspection raises ``TypeError``. Keeping runtime annotations here
is the smallest fix that lets every tool register cleanly.
"""

import asyncio
import logging
from typing import Any

from .client import CertIndexClient
from .validation import (
    McpValidationError,
    clamp_expiring_days,
    clamp_limit,
    clamp_page,
    validate_domain,
    validate_san,
    validate_sha256_hex,
    validate_substring,
)

logger = logging.getLogger("certindex_mcp")


def _build_server(client: CertIndexClient):
    """Construct and return a configured FastMCP server.

    Factored out of :func:`main` so unit tests can inject a stubbed
    :class:`CertIndexClient` (e.g. one backed by :mod:`respx`).
    """
    from mcp.server.fastmcp import FastMCP  # local import keeps `--help` cheap

    mcp = FastMCP("certindex")

    @mcp.tool()
    async def search_certificates(
        domain: str | None = None,
        cn: str | None = None,
        issuer: str | None = None,
        san: str | None = None,
        expired: bool | None = None,
        is_wildcard: bool | None = None,
        page: int = 1,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the CT certificate index by domain, CN, issuer, SAN,
        validity, or wildcard status. Returns a ``has_more`` boolean
        for paging (no unbounded COUNT)."""
        try:
            params = {
                "domain": validate_domain(domain) if domain else None,
                "cn": validate_substring(cn, parameter="cn"),
                "issuer": validate_substring(issuer, parameter="issuer"),
                "san": validate_san(san),
                "expired": expired,
                "is_wildcard": is_wildcard,
                "page": clamp_page(page),
                "limit": clamp_limit(limit),
            }
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get("/search_certificates", params=params)

    @mcp.tool()
    async def get_certificate(
        sha256: str, include_enrichment: bool = False
    ) -> dict[str, Any]:
        """Fetch a single cert by its 64-char hex SHA-256 fingerprint.

        Set ``include_enrichment=true`` to attach RDAP + DNS + ASN/hosting
        context for the cert's primary hostname under ``enrichment``."""
        try:
            sha = validate_sha256_hex(sha256)
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get(
            f"/get_certificate/{sha}",
            params={"include_enrichment": include_enrichment},
        )

    @mcp.tool()
    async def get_domain_certificates(
        domain: str,
        valid_only: bool = False,
        include_enrichment: bool = False,
        include_signals: bool = False,
        page: int = 1,
        limit: int = 10,
    ) -> dict[str, Any]:
        """List certificates for an exact domain name. Cold domains
        return a ``backfill_status`` sentinel; retry per the hint.

        Set ``include_enrichment=true`` to attach RDAP + DNS + ASN/hosting
        context for the domain under ``enrichment``.

        Set ``include_signals=true`` to also attach derived attribution
        signals under ``enrichment.signals`` (issuer_diversity_score,
        wildcard_breadth, third_party_vendors, weak_crypto_reasons).
        Implies enrichment. Requires a paid CertIndex plan (Pro or
        higher); free-tier keys get a ``tier_not_entitled`` error."""
        try:
            d = validate_domain(domain)
            params = {
                "valid_only": valid_only,
                "include_enrichment": include_enrichment,
                "include_signals": include_signals,
                "page": clamp_page(page),
                "limit": clamp_limit(limit),
            }
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get(f"/get_domain_certificates/{d}", params=params)

    @mcp.tool()
    async def get_subdomains(
        domain: str,
        page: int = 1,
        limit: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Enumerate unique subdomains seen in CT logs.

        Two pagination modes:

        * **Offset (default):** ``page``/``limit`` (limit clamped to 50),
          ordered by popularity (cert_count DESC).
        * **Cursor:** pass ``cursor=""`` (empty string) to start a keyset
          enumeration ordered by subdomain name ASC (stable against
          concurrent inserts; ``limit`` may go up to your tier ceiling).
          Then pass each response's ``next_cursor`` back until the
          response no longer carries a ``next_cursor`` value — that
          marks the terminal page. ``page`` is ignored in cursor mode.
        """
        try:
            d = validate_domain(domain)
            params: dict[str, Any] = {"page": clamp_page(page)}
            if cursor is not None:
                # Cursor mode: the server enforces the tier-aware limit
                # ceiling itself (up to 1000); don't pre-clamp to the
                # offset-mode maximum here. ``cursor=""`` must survive
                # to the wire (client only drops None-valued params).
                if not isinstance(limit, int) or isinstance(limit, bool):
                    return McpValidationError(
                        "limit", "must be an integer"
                    ).to_tool_error()
                params["limit"] = max(1, limit)
                params["cursor"] = cursor
            else:
                params["limit"] = clamp_limit(limit)
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get(f"/get_subdomains/{d}", params=params)

    @mcp.tool()
    async def get_latest_cert(
        domain: str,
        include_enrichment: bool = False,
        include_signals: bool = False,
    ) -> dict[str, Any]:
        """Most recent CURRENTLY-VALID cert for a domain (or
        ``{cert: null}`` with a backfill sentinel on cold domains).

        Currently-valid certificates are always preferred; a final leaf
        beats its precert twin. Only when the index holds NO
        currently-valid certificate is an expired one returned — then
        the response carries a top-level ``warning`` field. Never treat
        a response with ``warning`` set as the domain's active cert.

        Set ``include_enrichment=true`` to attach RDAP + DNS + ASN/hosting
        context for the domain under ``cert.enrichment``.

        Set ``include_signals=true`` to also attach derived attribution
        signals under ``cert.enrichment.signals`` (issuer_diversity_score,
        wildcard_breadth, third_party_vendors, weak_crypto_reasons).
        Implies enrichment. Requires a paid CertIndex plan (Pro or
        higher); free-tier keys get a ``tier_not_entitled`` error."""
        try:
            d = validate_domain(domain)
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get(
            f"/get_latest_cert/{d}",
            params={
                "include_enrichment": include_enrichment,
                "include_signals": include_signals,
            },
        )

    @mcp.tool()
    async def get_expiring_certs(domain: str, days: int = 30) -> dict[str, Any]:
        """Certificates for ``domain`` expiring within ``days`` days."""
        try:
            d = validate_domain(domain)
            params = {"days": clamp_expiring_days(days)}
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get(f"/get_expiring_certs/{d}", params=params)

    return mcp


def main() -> None:
    """CLI entry point — runs the MCP server over stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = CertIndexClient()
    server = _build_server(client)
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
