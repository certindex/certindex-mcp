"""MCP SDK v2 stdio entry point for certindex-mcp.

Ten tools that mirror the hosted CertIndex MCP surface
(``https://api.ctindex.io/mcp``). Each tool:

  1. Validates input client-side (rejects malformed hostnames /
     SHA-256s / overlong substrings before going to the wire).
  2. Forwards to ``GET /mcp-api/<tool>`` on the configured base URL
     (the async sweep tools use the canonical ``/v1/sweeps`` REST
     surface instead — ``POST /v1/sweeps`` / ``GET /v1/sweeps/{id}``).
  3. Returns the upstream JSON body verbatim, or a structured error
     dict on validation failure / HTTP error.

The entry point :func:`main` runs the server over stdio so any MCP
client (Claude Desktop, Continue, MCP Inspector, …) can spawn it.

NB: this module deliberately does NOT use ``from __future__ import
annotations``. Preserve runtime annotations for tool-schema introspection;
the stdio tests verify schemas and calls at the client-visible boundary.
"""

import asyncio
import logging
from typing import Any

from . import __version__
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
    """Construct and return a configured SDK v2 MCPServer.

    Factored out of :func:`main` so unit tests can inject a stubbed
    :class:`CertIndexClient` (e.g. one backed by :mod:`respx`).
    """
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("certindex", version=__version__)

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
        include_precerts: bool = False,
    ) -> dict[str, Any]:
        """Most recent CURRENTLY-VALID cert for a domain (or
        ``{cert: null}`` with a backfill sentinel on cold domains).

        Currently-valid certificates are always preferred. By default
        (``include_precerts=false``) a final (leaf) certificate always
        beats ANY precertificate — a precert is only returned when the
        index holds no final cert for the domain at all. Set
        ``include_precerts=true`` to let precerts compete on equal terms
        (newest issuance wins even if only its precert has been
        observed). Only when the index holds NO currently-valid
        certificate is an expired one returned — then the response
        carries a top-level ``warning`` field. Never treat a response
        with ``warning`` set as the domain's active cert.

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
                "include_precerts": include_precerts,
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

    @mcp.tool()
    async def submit_global_sweep(
        cn: str | None = None,
        san_contains: str | None = None,
        issuer: str | None = None,
        is_wildcard: bool | None = None,
        is_precert: bool | None = None,
        expired: bool | None = None,
        first_seen_after: str | None = None,
        first_seen_before: str | None = None,
        not_after_after: str | None = None,
        not_after_before: str | None = None,
        strict_attribution: bool | None = None,
        resume_token: str | None = None,
    ) -> dict[str, Any]:
        """Submit an asynchronous GLOBAL (domain-less) CN/SAN substring
        sweep of the entire index as a background job — the escape hatch
        when a global search exceeds the synchronous query budget.

        At least one of ``cn`` / ``san_contains`` is required (3+ chars);
        ``issuer`` may only be combined with one of them. Optional
        tri-state filters: ``is_wildcard`` / ``is_precert`` / ``expired``.
        Date bounds (``first_seen_*`` / ``not_after_*``) are ISO-8601.
        ``strict_attribution=true`` drops pure substring-collision rows.

        Returns ``{sweep_id, status, ...}`` — poll it with
        ``get_sweep_results``. Consumes one global-sweep quota unit per
        submission (quota varies by plan; free tier is not entitled).

        **Continuation:** when a finished sweep reports ``truncated:
        true``, submit a NEW sweep with the SAME filters plus
        ``resume_token`` set to the previous sweep's ``next_cursor`` to
        fetch the next chunk without gaps or duplicates."""
        try:
            body = {
                "cn": validate_substring(cn, parameter="cn"),
                "san_contains": validate_substring(
                    san_contains, parameter="san_contains"
                ),
                "issuer": validate_substring(issuer, parameter="issuer"),
                "is_wildcard": is_wildcard,
                "is_precert": is_precert,
                "expired": expired,
                "first_seen_after": first_seen_after,
                "first_seen_before": first_seen_before,
                "not_after_after": not_after_after,
                "not_after_before": not_after_before,
                "strict_attribution": strict_attribution,
                "resume_token": resume_token,
            }
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.post_v1("/sweeps", body=body)

    @mcp.tool()
    async def get_sweep_results(
        sweep_id: str, page: int = 1, limit: int = 100
    ) -> dict[str, Any]:
        """Poll an async sweep job by id; paginate its bounded result set
        once the job completes.

        While ``queued``/``running`` the response is status-only; when
        ``done`` it carries a page of results (same row shape as
        certificate search, plus a per-row ``match_class`` attribution
        annotation); when ``failed`` it carries the structured error. A
        ``done`` result with ``truncated: true`` also carries
        ``next_cursor`` — resubmit via ``submit_global_sweep`` with
        ``resume_token`` to continue past the result cap."""
        sid = (sweep_id or "").strip()
        if not sid:
            return McpValidationError("sweep_id", "is required").to_tool_error()
        try:
            params = {
                "page": clamp_page(page),
                "limit": max(1, min(int(limit), 1000)),
            }
        except (TypeError, ValueError):
            return McpValidationError("limit", "must be an integer").to_tool_error()
        return await client.get_v1(f"/sweeps/{sid}", params=params)

    @mcp.tool()
    async def get_usage() -> dict[str, Any]:
        """Return the caller's tier, current usage, remaining quota,
        billing period boundary, and add-on entitlements — lets an agent
        budget its own calls. Not rate-limited."""
        return await client.get("/usage")

    @mcp.tool()
    async def get_historical_backfill_status(domain: str) -> dict[str, Any]:
        """Check — and, when entitled, start or resume — the paid
        deep-historical certificate backfill for a domain.

        Active-cert lookups are always free and instant via the other
        tools; this covers the SEPARATE paid per-domain add-on that walks
        the full CT history. An un-entitled caller gets ``entitled:
        false`` and a hint; an entitled caller starts/resumes the deep
        walk and receives a wall-clock estimate plus live progress."""
        try:
            d = validate_domain(domain)
        except McpValidationError as exc:
            return exc.to_tool_error()
        return await client.get("/historical_backfill_status", params={"domain": d})

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
