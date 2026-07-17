"""Pins `ResolvedMCPCredentials.build_headers()`: the credential-header
precedence and the denylist filter on stored headers. Stored credentials must
never source a denylisted header (e.g. Host) — every consumer (chat's MCPTool,
the sandbox-proxy resolver) relies on this helper applying that filter."""

import json

import pytest

from onyx.db.mcp import ResolvedMCPCredentials
from onyx.db.models import MCPConnectionConfig
from onyx.utils.sensitive import SensitiveValue


def _sensitive(config_data: dict) -> SensitiveValue[dict]:
    """An ORM-loaded `config` column value: EncryptedJson wraps the stored
    JSON in a lazily-decrypted SensitiveValue."""
    return SensitiveValue(
        encrypted_bytes=json.dumps(config_data).encode(),
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


# `extract_connection_data` accepts both the ORM-loaded shape (SensitiveValue)
# and the plain dict a pre-flush `MCPConnectionConfig(config=...)` carries.
@pytest.mark.parametrize("wrap", [_sensitive, lambda d: d], ids=["loaded", "preflush"])
def test_build_headers_strips_denylisted_stored_headers(wrap) -> None:
    config = MCPConnectionConfig(
        config=wrap(
            {"headers": {"Authorization": "Bearer stored", "Host": "internal.evil"}}
        )
    )
    creds = ResolvedMCPCredentials(connection_config=config, user_oauth_token=None)

    assert creds.build_headers() == {"Authorization": "Bearer stored"}


def test_build_headers_pt_oauth_token_takes_precedence() -> None:
    config = MCPConnectionConfig(config={"headers": {"Authorization": "Bearer old"}})
    creds = ResolvedMCPCredentials(
        connection_config=config, user_oauth_token="login-token"
    )

    assert creds.build_headers() == {"Authorization": "Bearer login-token"}


def test_build_headers_empty_without_credentials() -> None:
    creds = ResolvedMCPCredentials(connection_config=None, user_oauth_token=None)

    assert creds.build_headers() == {}
