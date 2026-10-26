"""Header composition across templates, stored values, and generated auth."""

import json

import pytest

from onyx.db.enums import MCPAuthenticationType
from onyx.db.models import MCPConnectionConfig
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPConnectionData,
    MCPConnectionStatus,
)
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
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=config, user_oauth_token=None
    )

    assert creds.build_headers() == {"Authorization": "Bearer stored"}


def test_build_headers_pt_oauth_token_takes_precedence() -> None:
    config = MCPConnectionConfig(config={"headers": {"Authorization": "Bearer old"}})
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=config, user_oauth_token="login-token"
    )

    assert creds.build_headers() == {"Authorization": "Bearer login-token"}


def test_build_headers_empty_without_credentials() -> None:
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=None, user_oauth_token=None
    )

    assert creds.build_headers() == {}


def test_pt_oauth_merges_template_headers_and_overrides_authorization() -> None:
    config = MCPConnectionConfig(
        config={
            "headers": {"authorization": "Basic stale"},
            "header_substitutions": {"gateway_key": "gateway-secret"},
        }
    )
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=config,
        user_oauth_token="login-token",
        auth_type=MCPAuthenticationType.PT_OAUTH,
        auth_template=MCPAuthTemplate(
            headers={
                "X-Gateway-Key": "{gateway_key}",
                "X-User": "{user_email}",
            }
        ),
        user_email="alice@example.com",
    )

    assert creds.build_headers() == {
        "X-Gateway-Key": "gateway-secret",
        "X-User": "alice@example.com",
        "Authorization": "Bearer login-token",
    }
    assert creds.can_authenticate()


def test_oauth_merges_template_headers_with_token_auth() -> None:
    config = MCPConnectionConfig(
        config={
            "headers": {},
            "header_substitutions": {"gateway_key": "gateway-secret"},
            "tokens": {"token_type": "Bearer", "access_token": "oauth-token"},
        }
    )
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=config,
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.OAUTH,
        auth_template=MCPAuthTemplate(headers={"X-Gateway-Key": "{gateway_key}"}),
        user_email="alice@example.com",
    )

    assert creds.build_headers() == {
        "X-Gateway-Key": "gateway-secret",
        "Authorization": "Bearer oauth-token",
    }
    assert creds.can_authenticate()


def test_no_auth_template_requires_user_substitutions() -> None:
    template = MCPAuthTemplate(headers={"X-Gateway-Key": "{gateway_key}"})
    disconnected = ResolvedMCPCredentials.from_connection_config(
        connection_config=None,
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.NONE,
        auth_template=template,
        user_email="alice@example.com",
    )
    connected = ResolvedMCPCredentials.from_connection_config(
        connection_config=MCPConnectionConfig(
            config={
                "headers": {},
                "header_substitutions": {"gateway_key": "gateway-secret"},
            }
        ),
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.NONE,
        auth_template=template,
        user_email="alice@example.com",
    )

    assert not disconnected.can_authenticate()
    assert connected.can_authenticate()
    assert connected.build_headers() == {"X-Gateway-Key": "gateway-secret"}


def test_api_token_template_without_placeholders_needs_no_user_config() -> None:
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=None,
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_template=MCPAuthTemplate(headers={"X-Gateway-Key": "shared-key"}),
        user_email="alice@example.com",
    )

    assert creds.can_authenticate()
    assert creds.build_headers() == {"X-Gateway-Key": "shared-key"}


def test_fresh_template_rendering_overrides_persisted_auto_substitution() -> None:
    creds = ResolvedMCPCredentials.from_connection_config(
        connection_config=MCPConnectionConfig(
            config={"headers": {"X-User": "admin@example.com"}}
        ),
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_template=MCPAuthTemplate(headers={"X-User": "{user_email}"}),
        user_email="alice@example.com",
    )

    assert creds.build_headers() == {"X-User": "alice@example.com"}


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"headers": {}}, MCPConnectionStatus.NOT_CONNECTED),
        (
            {"headers": {}, "client_info": {"client_id": "registered"}},
            MCPConnectionStatus.NOT_CONNECTED,
        ),
        (
            {
                "headers": {},
                "tokens": {"access_token": "access", "token_type": "Bearer"},
            },
            MCPConnectionStatus.CONNECTED,
        ),
        (
            {
                "headers": {},
                "tokens": {"access_token": "access", "token_type": "Bearer"},
                "token_expires_at": 1,
            },
            MCPConnectionStatus.REAUTH_REQUIRED,
        ),
        (
            {
                "headers": {},
                "tokens": {
                    "access_token": "access",
                    "token_type": "Bearer",
                    "refresh_token": "refresh",
                },
                "token_expires_at": 1,
            },
            MCPConnectionStatus.CONNECTED,
        ),
        ({"headers": {}, "reauth_required": True}, MCPConnectionStatus.REAUTH_REQUIRED),
    ],
)
def test_oauth_connection_status(
    data: MCPConnectionData, expected: MCPConnectionStatus
) -> None:
    credentials = ResolvedMCPCredentials(
        connection_config_id=1,
        connection_data=data,
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.OAUTH,
    )
    assert credentials.connection_status() == expected
    assert credentials.can_authenticate() == (expected == MCPConnectionStatus.CONNECTED)


def test_existing_api_key_missing_new_required_field_needs_reauth() -> None:
    credentials = ResolvedMCPCredentials(
        connection_config_id=1,
        connection_data={"headers": {}, "header_substitutions": {"api_key": "old"}},
        user_oauth_token=None,
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_template=MCPAuthTemplate(
            headers={"Authorization": "Bearer {api_key}", "X-Org": "{organization}"}
        ),
    )
    assert credentials.connection_status() == MCPConnectionStatus.REAUTH_REQUIRED


@pytest.mark.parametrize("auth_type", [None, MCPAuthenticationType.NONE])
@pytest.mark.parametrize("rejected", [False, True])
def test_none_auth_missing_template_values_requires_setup(
    auth_type: MCPAuthenticationType | None, rejected: bool
) -> None:
    credentials = ResolvedMCPCredentials(
        connection_config_id=1,
        connection_data={
            "headers": {"X-Client": "onyx"},
            "header_substitutions": {"workspace": "existing"},
            "reauth_required": rejected,
        },
        user_oauth_token=None,
        auth_type=auth_type,
        auth_template=MCPAuthTemplate(
            headers={"X-Workspace": "{workspace}", "X-Org": "{organization}"}
        ),
    )
    assert not credentials.can_authenticate()
    assert credentials.connection_status() == (
        MCPConnectionStatus.REAUTH_REQUIRED
        if rejected
        else MCPConnectionStatus.NOT_CONNECTED
    )
