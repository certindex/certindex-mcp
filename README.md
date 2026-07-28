# certindex-mcp

<!-- mcp-name: io.github.certindex/certindex-mcp -->

[![CI](https://github.com/certindex/certindex-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/certindex/certindex-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/certindex-mcp.svg)](https://pypi.org/project/certindex-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) (Model Context Protocol) server
that exposes [CertIndex](https://ctindex.io)'s Certificate
Transparency search tools to any MCP-compatible client (Claude
Desktop, the MCP Inspector, Continue, etc.).

CertIndex indexes the full public CT corpus (~5 M certificates, growing
~100 k/day). This server wraps the public CertIndex REST API so an LLM
can ask questions like:

- "List every TLS certificate ever issued for `example.com`."
- "What subdomains has Let's Encrypt seen for `mycompany.io`?"
- "Show me certs expiring in the next 30 days for `api.mycompany.io`."
- "Pull the full PEM and CT log metadata for SHA-256 `<fingerprint>`."

## Why this repo exists

The CertIndex monorepo bundles an MCP server (mounted at
`https://api.ctindex.io/mcp`) that talks directly to the production
Postgres index. This standalone package is a thin **client-side**
shim: it speaks MCP to your editor / agent and forwards every tool
call to the hosted CertIndex REST API over HTTPS. Two consequences:

1. You don't need a copy of the index — sign up for a free API key
   at https://ctindex.io and you're done.
2. The package has a tiny dependency footprint (`mcp`, `httpx`,
   `pydantic`) — easy to audit, easy to vendor, no DB drivers.

## Install

```bash
pip install certindex-mcp
```

Or with [`uvx`](https://docs.astral.sh/uv/) for one-shot use:

```bash
uvx certindex-mcp
```

To install the latest development version from source instead:

```bash
pip install git+https://github.com/certindex/certindex-mcp
```

## Quickstart — Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "certindex": {
      "command": "uvx",
      "args": ["certindex-mcp"],
      "env": {
        "CERTINDEX_API_KEY": "ctx_live_..."
      }
    }
  }
}
```

Restart Claude Desktop. The ten CertIndex tools appear in the tool tray.

## Tools

Ten tools, matching the hosted CertIndex MCP server 1:1:

| Tool | What it does | Notable parameters |
| --- | --- | --- |
| `search_certificates` | Search the CT index by domain, CN, issuer, SAN, validity, or wildcard status. | `domain`, `cn`, `issuer`, `san`, `expired`, `is_wildcard`, `page`/`limit` |
| `get_certificate` | Fetch a single cert by SHA-256 fingerprint. | `sha256`, `include_enrichment` |
| `get_domain_certificates` | Every cert ever issued for an exact domain. | `valid_only`, `include_enrichment`, `include_signals` (paid plans), `page`/`limit` |
| `get_subdomains` | Enumerate unique subdomains seen in CT. | Offset (`page`/`limit`) **or** keyset cursor mode — pass `cursor=""` to start, then feed back each response's `next_cursor` |
| `get_latest_cert` | Most recent currently-valid cert for a domain. | `include_enrichment`, `include_signals`, `include_precerts` (let precertificates compete for "latest") |
| `get_expiring_certs` | Certs for a domain expiring within `days` days. | `days` |
| `submit_global_sweep` | Submit an async, domain-less CN/SAN substring sweep of the entire index (`POST /v1/sweeps`). | `cn`/`san_contains` (3+ chars, at least one required), `issuer`, `is_wildcard`, `is_precert`, `expired`, `first_seen_*`/`not_after_*` date bounds, `strict_attribution`, `resume_token` (continuation past the result cap) |
| `get_sweep_results` | Poll a sweep job and paginate its results when done (`GET /v1/sweeps/{id}`). | `sweep_id`, `page`/`limit` (up to 1,000) |
| `get_usage` | Caller's tier, current usage, remaining quota, and entitlements. | — |
| `get_historical_backfill_status` | Check / start the paid deep-history backfill for a domain. | `domain` |

## Quickstart — MCP Inspector

```bash
export CERTINDEX_API_KEY=ctx_live_...
npx @modelcontextprotocol/inspector uvx certindex-mcp
```

## Configuration

| Env var | Default | Description |
| --- | --- | --- |
| `CERTINDEX_API_KEY` | *(required)* | Your CertIndex API key. Mint one at https://ctindex.io/app/keys |
| `CERTINDEX_BASE_URL` | `https://api.ctindex.io` | Override for self-hosted deployments / staging |
| `CERTINDEX_TIMEOUT` | `30` | Per-request HTTP timeout (seconds) |

## Security

Input validation, rate-limit handling, and our supply-chain posture are
documented in [SECURITY.md](SECURITY.md). Please report vulnerabilities
to security@ctindex.io rather than filing public issues.

## Development

```bash
git clone https://github.com/certindex/certindex-mcp
cd certindex-mcp
pip install -e ".[dev]"
pytest
```

CI runs on Python 3.11 / 3.12 / 3.13.

## License

[MIT](LICENSE) © CertIndex contributors.
