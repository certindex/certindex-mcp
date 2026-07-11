"""Client-side input validation for certindex-mcp.

These validators are an exact mirror of the server-side validators in
the CertIndex monorepo (``api/mcp_validation.py``). We duplicate them
here so that:

  1. Invalid input is rejected **before** a network round-trip — the
     LLM gets immediate feedback and the upstream service never sees
     malformed traffic.
  2. The package can be audited independently without cloning the
     server monorepo.

When the two implementations diverge, the server-side validators are
authoritative — the worst that can happen with a stale client copy is
a redundant 422 from the server.
"""
from __future__ import annotations

import re


class McpValidationError(ValueError):
    """Raised when a tool parameter fails validation."""

    def __init__(self, parameter: str, reason: str) -> None:
        super().__init__(f"{parameter}: {reason}")
        self.parameter = parameter
        self.reason = reason

    def to_tool_error(self) -> dict:
        return {
            "error": "invalid_parameter",
            "parameter": self.parameter,
            "message": self.reason,
        }


DOMAIN_MAX_LEN = 253
LABEL_MAX_LEN = 63
SHA256_HEX_LEN = 64
SUBSTR_MAX_LEN = 255
PAGE_MAX = 10_000
LIMIT_MAX = 50
EXPIRING_DAYS_MAX = 365

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_DOMAIN_RE = re.compile(rf"^(?:{_LABEL}\.)+{_LABEL}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUBSTR_RE = re.compile(r"^[A-Za-z0-9 .,/&'()\-]+$")


def validate_domain(value: str, *, parameter: str = "domain") -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpValidationError(parameter, "value is required")
    v = value.strip().lower()
    if v.startswith("*."):
        v = v[2:]
    if not v:
        raise McpValidationError(parameter, "value is required")
    if len(v) > DOMAIN_MAX_LEN:
        raise McpValidationError(parameter, f"length exceeds {DOMAIN_MAX_LEN} octets")
    if any(len(label) > LABEL_MAX_LEN for label in v.split(".")):
        raise McpValidationError(parameter, f"label exceeds {LABEL_MAX_LEN} octets")
    if not _DOMAIN_RE.match(v):
        raise McpValidationError(
            parameter,
            "must be a well-formed registrable hostname "
            "(LDH labels separated by dots; no IP literals, ports, or paths)",
        )
    if v.split(".")[-1].isdigit():
        raise McpValidationError(
            parameter,
            "must be a well-formed registrable hostname "
            "(IP literals are not accepted)",
        )
    return v


def validate_sha256_hex(value: str, *, parameter: str = "sha256") -> str:
    if not isinstance(value, str):
        raise McpValidationError(parameter, "value is required")
    v = value.strip().lower()
    if len(v) != SHA256_HEX_LEN or not _SHA256_RE.match(v):
        raise McpValidationError(
            parameter,
            f"must be a {SHA256_HEX_LEN}-character lowercase hex SHA-256 fingerprint",
        )
    return v


def validate_substring(value: str | None, *, parameter: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise McpValidationError(parameter, "value must be a string")
    v = value.strip()
    if not v:
        return None
    if len(v) > SUBSTR_MAX_LEN:
        raise McpValidationError(parameter, f"length exceeds {SUBSTR_MAX_LEN} characters")
    if not _SUBSTR_RE.match(v):
        raise McpValidationError(
            parameter,
            "contains disallowed characters "
            "(allowed: letters, digits, spaces, and . , / & ' ( ) -)",
        )
    return v


def validate_san(value: str | None) -> str | None:
    """Exact-match SAN filter. Preserves a leading ``*.`` wildcard
    so wildcard SAN entries round-trip verbatim — without this, the
    apex would be queried instead and wildcard SANs would silently
    become unmatchable. Mirror of the server-side ``validate_san``.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise McpValidationError("san", "value must be a string")
    raw = value.strip().lower()
    if not raw:
        return None
    if raw.startswith("*."):
        apex = raw[2:]
        validate_domain(apex, parameter="san")
        return "*." + apex
    return validate_domain(raw, parameter="san")


def clamp_limit(value: int, *, parameter: str = "limit") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise McpValidationError(parameter, "must be an integer")
    return max(1, min(LIMIT_MAX, value))


def clamp_page(value: int, *, parameter: str = "page") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise McpValidationError(parameter, "must be an integer")
    if value < 1:
        raise McpValidationError(parameter, "must be >= 1")
    if value > PAGE_MAX:
        raise McpValidationError(parameter, f"must be <= {PAGE_MAX}")
    return value


def clamp_expiring_days(value: int, *, parameter: str = "days") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise McpValidationError(parameter, "must be an integer")
    return max(1, min(EXPIRING_DAYS_MAX, value))
