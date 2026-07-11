"""Mirror of the server-side validator tests, kept in-package so the
distribution can be audited without cloning the server monorepo."""
from __future__ import annotations

import pytest

from certindex_mcp.validation import (
    LIMIT_MAX,
    SHA256_HEX_LEN,
    McpValidationError,
    clamp_expiring_days,
    clamp_limit,
    clamp_page,
    validate_domain,
    validate_san,
    validate_sha256_hex,
    validate_substring,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("example.com", "example.com"),
        ("  EXAMPLE.COM  ", "example.com"),
        ("*.example.com", "example.com"),
        ("api.v2.example.co.uk", "api.v2.example.co.uk"),
    ],
)
def test_validate_domain_accepts(raw, expected):
    assert validate_domain(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "", "   ", "localhost", "example.com:8080", "http://example.com",
        "user@example.com", "example..com", "-x.com", "x-.com",
        "exa mple.com", "exa%mple.com", "exa_mple.com", "a" * 64 + ".com",
    ],
)
def test_validate_domain_rejects(bad):
    with pytest.raises(McpValidationError):
        validate_domain(bad)


def test_validate_sha256_accepts():
    h = "a" * SHA256_HEX_LEN
    assert validate_sha256_hex(h.upper()) == h


@pytest.mark.parametrize("bad", ["", "abc", "g" * SHA256_HEX_LEN, "a" * 63])
def test_validate_sha256_rejects(bad):
    with pytest.raises(McpValidationError):
        validate_sha256_hex(bad)


def test_validate_substring_empty_is_none():
    assert validate_substring("", parameter="cn") is None
    assert validate_substring(None, parameter="cn") is None


@pytest.mark.parametrize("bad", ["a%b", "a_b", "x\x00y", "drop;table"])
def test_validate_substring_rejects(bad):
    with pytest.raises(McpValidationError):
        validate_substring(bad, parameter="cn")


def test_validate_san_preserves_wildcard_prefix():
    """Parity guard with the in-tree validator: wildcard SANs are
    first-class CT entries and must round-trip verbatim through the
    OSS shim, otherwise ``search_certificates(san='*.example.com')``
    would silently rewrite to the apex and miss wildcard SAN rows."""
    assert validate_san("*.example.com") == "*.example.com"
    assert validate_san("  *.EXAMPLE.com  ") == "*.example.com"
    assert validate_san("api.example.com") == "api.example.com"
    assert validate_san(None) is None
    assert validate_san("") is None
    with pytest.raises(McpValidationError):
        validate_san("not a domain")


def test_validate_domain_rejects_leading_dots_or_stars():
    """Regression: a previous ``lstrip('*.')`` implementation silently
    normalised ``.example.com`` and ``**.example.com`` to the apex."""
    with pytest.raises(McpValidationError):
        validate_domain(".example.com")
    with pytest.raises(McpValidationError):
        validate_domain("*..example.com")
    with pytest.raises(McpValidationError):
        validate_domain("**.example.com")


def test_numeric_clamps():
    assert clamp_limit(0) == 1
    assert clamp_limit(LIMIT_MAX + 99) == LIMIT_MAX
    assert clamp_page(1) == 1
    with pytest.raises(McpValidationError):
        clamp_page(0)
    assert clamp_expiring_days(99999) == 365
