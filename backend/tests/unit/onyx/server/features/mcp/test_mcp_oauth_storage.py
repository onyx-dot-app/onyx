import asyncio
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator, cast
from unittest.mock import MagicMock, call

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken
from pydantic import AnyHttpUrl

from onyx.db.enums import MCPOAuthProviderMode, MCPTransport
from onyx.db.models import MCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth
from onyx.server.features.mcp.models import MCPOAuthKeys

_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"
_DISCOVERED_METADATA = OAuthMetadata(
    issuer=cast(AnyHttpUrl, "https://idp.other-host.com"),
    authorization_endpoint=cast(AnyHttpUrl, "https://idp.other-host.com/authorize"),
    token_endpoint=cast(AnyHttpUrl, "https://idp.other-host.com/token"),
)


def _client_information(client_id: str = "client-id") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=f"{client_id}-secret",
        redirect_uris=[_REDIRECT_URI],
        token_endpoint_auth_method="client_secret_post",
    )


def _server(provider_mode: MCPOAuthProviderMode) -> MCPServer:
    known_provider = provider_mode is MCPOAuthProviderMode.KNOWN_PROVIDER
    return cast(
        MCPServer,
        SimpleNamespace(
            id=42,
            name="Protected MCP",
            server_url="https://mcp.example.com/mcp",
            transport=MCPTransport.STREAMABLE_HTTP,
            oauth_provider_mode=provider_mode,
            oauth_authorization_endpoint=(
                "https://accounts.example.com/authorize" if known_provider else None
            ),
            oauth_token_endpoint=(
                "https://accounts.example.com/token" if known_provider else None
            ),
        ),
    )


def _provider(
    provider_mode: MCPOAuthProviderMode,
    *,
    load_stored_tokens: bool = True,
) -> oauth.OnyxOAuthClientProvider:
    return oauth.make_oauth_provider(
        _server(provider_mode),
        connection_config_id=101,
        shared_client_config_id=None,
        load_stored_tokens=load_stored_tokens,
    )


def _patch_config_read(
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict[str, Any],
) -> None:
    @contextmanager
    def fake_session() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(oauth, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(
        oauth,
        "get_connection_config_by_id",
        lambda *_args, **_kwargs: SimpleNamespace(id=101),
    )
    monkeypatch.setattr(oauth, "extract_connection_data", lambda _config: config_data)


def test_authorization_result_does_not_inherit_previous_grants_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = _client_information("same-client")
    config_data: dict[str, Any] = {
        MCPOAuthKeys.CLIENT_INFO.value: registration.model_dump(mode="json"),
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "existing-access-token",
            "refresh_token": "existing-refresh-token",
            "token_type": "Bearer",
        },
    }
    _patch_config_read(monkeypatch, config_data)
    get_config = MagicMock(return_value=SimpleNamespace(id=101))
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "get_connection_config_by_id", get_config)
    monkeypatch.setattr(oauth, "update_connection_config", update_config)
    asyncio.run(
        oauth.OnyxTokenStorage(101).set_authorization_result(
            OAuthToken(access_token="new-access-token", token_type="Bearer"),
            registration,
        )
    )

    assert get_config.call_args.kwargs["for_update"] is True
    persisted = update_config.call_args.args[2]
    assert persisted[MCPOAuthKeys.CLIENT_INFO.value] == (
        registration.model_dump(mode="json")
    )
    assert persisted[MCPOAuthKeys.TOKENS.value]["refresh_token"] is None


def test_authorization_result_rejects_a_replaced_client_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_data: dict[str, Any] = {
        MCPOAuthKeys.CLIENT_INFO.value: _client_information(
            "replacement-client"
        ).model_dump(mode="json"),
    }
    _patch_config_read(monkeypatch, config_data)
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config", update_config)

    with pytest.raises(OnyxError, match="client registration changed"):
        asyncio.run(
            oauth.OnyxTokenStorage(
                101,
                expected_client_information_fingerprint=(
                    oauth.mcp_oauth_client_information_fingerprint(
                        _client_information("original-client")
                    )
                ),
            ).set_authorization_result(
                OAuthToken(access_token="new-access-token", token_type="Bearer"),
                _client_information("original-client"),
            )
        )

    update_config.assert_not_called()


def test_refresh_write_is_skipped_after_a_new_grant_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_data: dict[str, Any] = {
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "new-grant-access-token",
            "refresh_token": "new-grant-refresh-token",
            "token_type": "Bearer",
        }
    }
    _patch_config_read(monkeypatch, config_data)
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config", update_config)

    persisted = asyncio.run(
        oauth.OnyxTokenStorage(101).set_refreshed_tokens(
            OAuthToken(
                access_token="late-refresh-access-token",
                refresh_token="rotated-refresh-token",
                token_type="Bearer",
            ),
            redeemed_refresh_token="old-refresh-token",
        )
    )

    assert persisted is False
    update_config.assert_not_called()


def test_authorization_result_rejects_changed_routing_headers_at_write_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = _client_information()
    config_data: dict[str, Any] = {
        "headers": {"X-Gateway-Tenant": "replacement-tenant"},
        MCPOAuthKeys.CLIENT_INFO.value: registration.model_dump(mode="json"),
    }
    _patch_config_read(monkeypatch, config_data)
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config", update_config)

    with pytest.raises(OnyxError, match="connection headers changed"):
        asyncio.run(
            oauth.OnyxTokenStorage(
                101,
                expected_connection_headers_fingerprint=(
                    oauth.mcp_oauth_connection_headers_fingerprint(
                        {"X-Gateway-Tenant": "original-tenant"}
                    )
                ),
            ).set_authorization_result(
                OAuthToken(access_token="new-access-token", token_type="Bearer"),
                registration,
            )
        )

    update_config.assert_not_called()


def test_client_fingerprint_is_stable_for_nested_object_key_order() -> None:
    first = _client_information().model_copy(
        update={"jwks": {"keys": [{"kid": "one", "kty": "RSA"}], "version": 1}}
    )
    second = _client_information().model_copy(
        update={"jwks": {"version": 1, "keys": [{"kty": "RSA", "kid": "one"}]}}
    )

    assert oauth.mcp_oauth_client_information_fingerprint(first) == (
        oauth.mcp_oauth_client_information_fingerprint(second)
    )


def test_shared_client_lookup_does_not_write_stale_user_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_config = SimpleNamespace(id=101)
    shared_config = SimpleNamespace(id=100)
    registration = _client_information("shared-registration")
    config_data_by_id = {
        101: {"headers": {"X-Gateway-Tenant": "tenant-1"}},
        100: {MCPOAuthKeys.CLIENT_INFO.value: registration.model_dump(mode="json")},
    }

    @contextmanager
    def fake_session() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(oauth, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(
        oauth,
        "get_connection_config_by_id",
        lambda config_id, *_args, **_kwargs: (
            user_config if config_id == 101 else shared_config
        ),
    )
    monkeypatch.setattr(
        oauth,
        "extract_connection_data",
        lambda config: config_data_by_id[config.id],
    )
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config", update_config)
    storage = oauth.OnyxTokenStorage(101, shared_client_config_id=100)

    assert asyncio.run(storage.get_client_info()) == registration
    update_config.assert_not_called()


def test_client_registration_isolated_to_each_locked_configuration_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    configs = {101: SimpleNamespace(id=101), 100: SimpleNamespace(id=100)}
    config_data = {
        101: {
            MCPOAuthKeys.TOKENS.value: {"access_token": "user-token"},
            "headers": {"Authorization": "Bearer user-token"},
        },
        100: {"unrelated": "preserved"},
    }

    @contextmanager
    def fake_session() -> Iterator[object]:
        yield session

    get_config = MagicMock(
        side_effect=lambda config_id, *_args, **_kwargs: configs[config_id]
    )
    monkeypatch.setattr(oauth, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(oauth, "get_connection_config_by_id", get_config)
    monkeypatch.setattr(
        oauth, "extract_connection_data", lambda config: config_data[config.id]
    )
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config__no_commit", update_config)
    storage = oauth.OnyxTokenStorage(101, shared_client_config_id=100)
    registration = _client_information("new-registration")

    asyncio.run(storage.set_client_info(registration))

    assert get_config.call_args_list == [
        call(100, session, for_update=True),
        call(101, session, for_update=True),
    ]
    expected_registration = registration.model_dump(mode="json")
    assert config_data[101][MCPOAuthKeys.CLIENT_INFO.value] == expected_registration
    assert config_data[100] == {
        "unrelated": "preserved",
        MCPOAuthKeys.CLIENT_INFO.value: expected_registration,
    }
    assert update_config.call_count == 2
    session.commit.assert_called_once_with()


def test_concurrent_registration_adopts_the_shared_winner_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    configs = {101: SimpleNamespace(id=101), 100: SimpleNamespace(id=100)}
    winner = _client_information("winning-registration")
    config_data = {
        101: {"headers": {"X-Gateway-Tenant": "tenant-1"}},
        100: {
            MCPOAuthKeys.CLIENT_INFO.value: winner.model_dump(mode="json"),
        },
    }

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield session

    monkeypatch.setattr(oauth, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(
        oauth,
        "get_connection_config_by_id",
        lambda config_id, *_args, **_kwargs: configs[config_id],
    )
    monkeypatch.setattr(
        oauth, "extract_connection_data", lambda config: config_data[config.id]
    )
    update_config = MagicMock()
    monkeypatch.setattr(oauth, "update_connection_config__no_commit", update_config)

    with pytest.raises(oauth.MCPClientRegistrationConflict):
        asyncio.run(
            oauth.OnyxTokenStorage(101, shared_client_config_id=100).set_client_info(
                _client_information("losing-registration")
            )
        )

    assert config_data[101][MCPOAuthKeys.CLIENT_INFO.value] == (
        winner.model_dump(mode="json")
    )
    assert config_data[100][MCPOAuthKeys.CLIENT_INFO.value] == (
        winner.model_dump(mode="json")
    )
    session.commit.assert_called_once_with()


def test_token_load_hydrates_expiry_used_by_the_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    expired_at = time.time() - 60
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.TOKEN_EXPIRES_AT.value: expired_at,
            MCPOAuthKeys.TOKENS.value: {
                "access_token": "expired-token",
                "token_type": "Bearer",
            },
        },
    )

    tokens = asyncio.run(provider.context.storage.get_tokens())
    provider.context.current_tokens = tokens

    assert provider.context.token_expiry_time == expired_at
    assert provider.context.is_token_valid() is False


def test_reauthentication_ignores_tokens_but_rehydrates_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(
        MCPOAuthProviderMode.AUTO_DISCOVERY,
        load_stored_tokens=False,
    )
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.TOKENS.value: {
                "access_token": "current-token",
                "token_type": "Bearer",
            },
            MCPOAuthKeys.METADATA.value: _DISCOVERED_METADATA.model_dump(mode="json"),
        },
    )

    assert asyncio.run(provider.context.storage.get_tokens()) is None
    assert provider.context.oauth_metadata == _DISCOVERED_METADATA


def test_token_load_clears_stale_expiry_when_storage_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    provider.context.token_expiry_time = 999.0
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.TOKENS.value: {
                "access_token": "current-token",
                "token_type": "Bearer",
            }
        },
    )

    asyncio.run(provider.context.storage.get_tokens())

    assert provider.context.token_expiry_time is None


def test_token_load_does_not_override_known_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.METADATA.value: _DISCOVERED_METADATA.model_dump(mode="json"),
            MCPOAuthKeys.TOKENS.value: {
                "access_token": "current-token",
                "token_type": "Bearer",
            },
        },
    )

    asyncio.run(provider.context.storage.get_tokens())

    assert provider.context.oauth_metadata is not None
    assert (
        str(provider.context.oauth_metadata.token_endpoint)
        == "https://accounts.example.com/token"
    )


def test_token_write_persists_discovered_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    provider.context.oauth_metadata = _DISCOVERED_METADATA
    config_data: dict[str, Any] = {}
    _patch_config_read(monkeypatch, config_data)
    monkeypatch.setattr(oauth, "update_connection_config", MagicMock())

    asyncio.run(
        provider.context.storage.set_tokens(
            OAuthToken(
                access_token="current-token",
                token_type="Bearer",
                expires_in=3600,
            )
        )
    )

    assert config_data[MCPOAuthKeys.METADATA.value] == (
        _DISCOVERED_METADATA.model_dump(mode="json")
    )
