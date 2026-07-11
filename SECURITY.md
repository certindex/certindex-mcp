# Security Policy

## Reporting a vulnerability

Please email **security@ctindex.io** with details. Do **not** open a
public GitHub issue for security-sensitive reports. We aim to acknowledge
within 48 hours and to ship a fix or coordinated disclosure timeline
within 14 days for high-severity reports.

## Threat model

`certindex-mcp` is a client-side MCP shim. The threat surface is
deliberately small:

| Surface | Posture |
| --- | --- |
| **Auth** | Single bearer-token (API key) read from `CERTINDEX_API_KEY`. Never logged. |
| **Transport** | HTTPS only; certificate verification cannot be disabled. |
| **Outbound HTTP** | Every request goes to `CERTINDEX_BASE_URL` (default `https://api.ctindex.io`). No user input is interpolated into the URL host or scheme. |
| **Input validation** | All tool parameters go through `certindex_mcp.validation` (strict hostname regex, SHA-256 hex regex, substring length caps) before reaching the wire. The same validators are used server-side. |
| **SSRF** | Not directly exposed — the package only talks to a single configured base URL. |
| **SQL injection** | N/A — package never builds SQL; the hosted API uses parameterised queries. |
| **Supply chain** | Three runtime deps (`mcp`, `httpx`, `pydantic`). CI runs `pip-audit` on every push. Releases are built and published from a GitHub Actions workflow with provenance attestations. |

## What this package will NOT do

* Read your filesystem.
* Make outbound requests to any host other than `CERTINDEX_BASE_URL`.
* Log your API key, even at DEBUG.
* Cache certificate bodies to disk.

## Supported versions

The latest minor release on PyPI receives security fixes. Older minors
are best-effort. Pin to the latest patch in `^x.y.z`.

## Coordinated disclosure

If you would like credit in the release notes, include your preferred
handle and (optionally) a homepage URL in your report. Anonymous
reports are equally welcome.
