import hashlib
import re
from typing import cast

import pytest

from onyx.auth.constants import (
    OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX,
    OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX,
    PAT_PREFIX,
)
from onyx.auth.oauth_provider import (
    OAuthProviderTokenKind,
    generate_oauth_provider_token,
    parse_oauth_provider_token,
)
from onyx.auth.pat import hash_pat

_URLSAFE_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        (OAuthProviderTokenKind.ACCESS, OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX),
        (OAuthProviderTokenKind.REFRESH, OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX),
    ],
)
def test_generate_parse_roundtrip_for_each_kind(
    kind: OAuthProviderTokenKind, prefix: str
) -> None:
    token = generate_oauth_provider_token("tenant_1-A", kind)

    tenant_segment, secret = token.removeprefix(prefix).split(".")
    assert tenant_segment == "tenant_1-A"
    assert _URLSAFE_SECRET_RE.fullmatch(secret) is not None

    parsed = parse_oauth_provider_token(token)
    assert parsed is not None
    assert parsed.tenant_id == "tenant_1-A"
    assert parsed.kind == kind
    assert parsed.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_generate_oauth_provider_token_returns_unique_values() -> None:
    tokens = {
        generate_oauth_provider_token("tenant", OAuthProviderTokenKind.ACCESS)
        for _ in range(32)
    }

    assert len(tokens) == 32


def test_hash_oauth_provider_token_hashes_full_wire_token() -> None:
    token = generate_oauth_provider_token("tenant", OAuthProviderTokenKind.ACCESS)
    token_hash = hash_pat(token)

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
def test_generate_oauth_provider_token_rejects_invalid_tenants(tenant_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid OAuth provider tenant ID"):
        generate_oauth_provider_token(tenant_id, OAuthProviderTokenKind.ACCESS)


def test_generate_oauth_provider_token_rejects_invalid_token_kind() -> None:
    invalid_kind = cast(OAuthProviderTokenKind, "bogus")

    with pytest.raises(ValueError, match="Invalid OAuth provider token kind"):
        generate_oauth_provider_token("tenant", invalid_kind)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "ordinary-session-token",
        PAT_PREFIX + "tenant." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant",
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 44),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "=",
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant.hasdot." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant/has-slash." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant%2Edot." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant%2Fslash." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "unicodé." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "é",
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "/",
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 42) + "\n",
        OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX + "tenant." + ("a" * 42),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX.removesuffix("_") + "r_tenant." + ("a" * 43),
        OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX + "tenant." + ("a" * 43) + ".extra",
    ],
)
def test_parse_oauth_provider_token_rejects_malformed_inputs(token: str) -> None:
    assert parse_oauth_provider_token(token) is None


def test_parse_oauth_provider_token_hash_changes_when_tenant_is_tampered() -> None:
    token = generate_oauth_provider_token("tenant-a", OAuthProviderTokenKind.ACCESS)
    tampered = token.replace("tenant-a", "tenant-b", 1)

    parsed = parse_oauth_provider_token(token)
    parsed_tampered = parse_oauth_provider_token(tampered)

    assert parsed is not None
    assert parsed_tampered is not None
    assert parsed.tenant_id == "tenant-a"
    assert parsed_tampered.tenant_id == "tenant-b"
    assert parsed.token_hash != parsed_tampered.token_hash
