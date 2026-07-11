# certindex-mcp

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

Restart Claude Desktop. The six CertIndex tools (`search_certificates`,
`get_certificate`, `get_domain_certificates`, `get_subdomains`,
`get_latest_cert`, `get_expiring_certs`) appear in the tool tray.

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
