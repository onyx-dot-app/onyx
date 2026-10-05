import hashlib
import re
from typing import cast

import pytest

from onyx.auth.constants import (
    MCP_OAUTH_ACCESS_TOKEN_PREFIX,
    MCP_OAUTH_REFRESH_TOKEN_PREFIX,
    PAT_PREFIX,
)
from onyx.auth.mcp_oauth import (
    MCPOAuthTokenKind,
    generate_mcp_oauth_token,
    hash_mcp_oauth_token,
    parse_mcp_oauth_token,
)

_URLSAFE_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        (MCPOAuthTokenKind.ACCESS, MCP_OAUTH_ACCESS_TOKEN_PREFIX),
        (MCPOAuthTokenKind.REFRESH, MCP_OAUTH_REFRESH_TOKEN_PREFIX),
    ],
)
def test_generate_parse_roundtrip_for_each_kind(
    kind: MCPOAuthTokenKind, prefix: str
) -> None:
    token = generate_mcp_oauth_token("tenant_1-A", kind)

    tenant_segment, secret = token.removeprefix(prefix).split(".")
    assert tenant_segment == "tenant_1-A"
    assert _URLSAFE_SECRET_RE.fullmatch(secret) is not None

    parsed = parse_mcp_oauth_token(token)
    assert parsed is not None
    assert parsed.tenant_id == "tenant_1-A"
    assert parsed.kind == kind
    assert parsed.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_generate_mcp_oauth_token_returns_unique_values() -> None:
    tokens = {
        generate_mcp_oauth_token("tenant", MCPOAuthTokenKind.ACCESS) for _ in range(32)
    }

    assert len(tokens) == 32


def test_hash_mcp_oauth_token_hashes_full_wire_token() -> None:
    token = generate_mcp_oauth_token("tenant", MCPOAuthTokenKind.ACCESS)
    token_hash = hash_mcp_oauth_token(token)

    assert token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in token_hash
    assert len(token_hash) == 64


@pytest.mark.parametrize(
    "tenant_id",
    [
        "",
        "has.dot",
        "has/slash",
        "has%2Fslash",
        "has space",
        "has\nnewline",
        "unicodé",
        "a" * 64,
    ],
)
def test_generate_mcp_oauth_token_rejects_invalid_tenants(tenant_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid MCP OAuth tenant ID"):
        generate_mcp_oauth_token(tenant_id, MCPOAuthTokenKind.ACCESS)


def test_generate_mcp_oauth_token_rejects_invalid_token_kind() -> None:
    invalid_kind = cast(MCPOAuthTokenKind, "bogus")

    with pytest.raises(ValueError, match="Invalid MCP OAuth token kind"):
        generate_mcp_oauth_token("tenant", invalid_kind)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "ordinary-session-token",
        PAT_PREFIX + "tenant." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant",
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 44),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "=",
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant.hasdot." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant/has-slash." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant%2Edot." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant%2Fslash." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "unicodé." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "é",
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "/",
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "\n",
        MCP_OAUTH_REFRESH_TOKEN_PREFIX + "tenant." + ("a" * 42),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX.removesuffix("_") + "r_tenant." + ("a" * 43),
        MCP_OAUTH_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 43) + ".extra",
    ],
)
def test_parse_mcp_oauth_token_rejects_malformed_inputs(token: str) -> None:
    assert parse_mcp_oauth_token(token) is None


def test_parse_mcp_oauth_token_hash_changes_when_tenant_is_tampered() -> None:
    token = generate_mcp_oauth_token("tenant-a", MCPOAuthTokenKind.ACCESS)
    tampered = token.replace("tenant-a", "tenant-b", 1)

    parsed = parse_mcp_oauth_token(token)
    parsed_tampered = parse_mcp_oauth_token(tampered)

    assert parsed is not None
    assert parsed_tampered is not None
    assert parsed.tenant_id == "tenant-a"
    assert parsed_tampered.tenant_id == "tenant-b"
    assert parsed.token_hash != parsed_tampered.token_hash
