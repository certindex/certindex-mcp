# Changelog

## 0.2.1 (unreleased)

- Restrict the existing FastMCP implementation to MCP SDK 1.x
  (`mcp>=1.2.0,<2`) so a fresh install cannot resolve the incompatible SDK 2.x.
- Synchronize package, runtime, user-agent and MCP registry version metadata.
- Add installed-console-script stdio tests for initialization, the exact ten
  tools, a successful HTTP-backed call, local validation, and upstream errors.
- Test the built wheel in a clean environment on every CI Python version.

Release gate: merge and publish only after approval. After PyPI publication,
verify a fresh public install via initialize, tools/list and tools/call before
closing the tracking issue. Tests use only a loopback HTTP fixture; they do not
prove production authentication, entitlements or data coverage.
