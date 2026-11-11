"""Connection failures never reach the setup publication transaction."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import MCPSetupRequest


@pytest.fixture
def setup_request() -> MCPSetupRequest:
    return MCPSetupRequest(
        name="Draft server",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
    )


@pytest.fixture
def actor() -> User:
    return User(id=uuid4(), email="owner@example.com")


@pytest.fixture
def publish(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    publish = MagicMock()
    monkeypatch.setattr(api, "_publish_mcp_setup", publish)
    monkeypatch.setattr(api, "_validate_mcp_setup", MagicMock())
    monkeypatch.setattr(api, "_mcp_setup_headers", MagicMock(return_value={}))
    return publish


def test_start_failure_never_publishes(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "start_setup_oauth",
        AsyncMock(side_effect=ValueError("registration failed")),
    )
    with pytest.raises(OnyxError) as error:
        asyncio.run(api.setup_mcp_server(setup_request, MagicMock(), actor))
    assert error.value.extra == {"oauth_error": "oauth_failed"}
    publish.assert_not_called()


def test_pending_authorization_never_publishes(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "start_setup_oauth",
        AsyncMock(
            return_value=(
                MagicMock(),
                MagicMock(),
                "https://auth.example.com/authorize",
            )
        ),
    )
    discovery = MagicMock()
    monkeypatch.setattr(api, "discover_mcp_tools", discovery)
    response = asyncio.run(api.setup_mcp_server(setup_request, MagicMock(), actor))
    assert response.status == "authorization_required"
    publish.assert_not_called()
    discovery.assert_not_called()


@pytest.mark.parametrize("oauth", [False, True])
def test_discovery_failure_never_publishes(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    oauth: bool,
) -> None:
    if not oauth:
        setup_request.auth_type = MCPAuthenticationType.NONE
    monkeypatch.setattr(
        api,
        "start_setup_oauth",
        AsyncMock(return_value=(MagicMock(), MagicMock(), None)),
    )
    monkeypatch.setattr(
        api,
        "discover_mcp_tools",
        MagicMock(side_effect=ValueError("tools unavailable")),
    )
    with pytest.raises(ValueError, match="tools unavailable"):
        asyncio.run(api.setup_mcp_server(setup_request, MagicMock(), actor))
    publish.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["denied", "permission", "stale", "exchange", "discovery"]
)
def test_failed_callback_never_publishes(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    attempt = MagicMock(request=setup_request, expected_configuration_fingerprint=None)
    consume = MagicMock(return_value=attempt)
    exchange = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(api, "consume_setup_oauth", consume)
    monkeypatch.setattr(api, "complete_setup_oauth", exchange)
    monkeypatch.setattr(api, "_assert_mcp_setup_current", MagicMock())
    monkeypatch.setattr(api, "discover_mcp_tools", MagicMock())
    if failure == "permission":
        monkeypatch.setattr(
            api,
            "_validate_mcp_setup",
            MagicMock(side_effect=ValueError("permission revoked")),
        )
    elif failure == "stale":
        monkeypatch.setattr(
            api,
            "_assert_mcp_setup_current",
            MagicMock(side_effect=ValueError("configuration changed")),
        )
    elif failure == "exchange":
        exchange.side_effect = ValueError("token exchange failed")
    elif failure == "discovery":
        monkeypatch.setattr(
            api,
            "discover_mcp_tools",
            MagicMock(side_effect=ValueError("tools unavailable")),
        )
    callback = {"state": "mcp-setup_attempt", "code": "code"}
    if failure == "denied":
        callback["error"] = "access_denied"
    with pytest.raises((OnyxError, ValueError)):
        asyncio.run(api._complete_mcp_setup(callback, MagicMock(), actor))
    consume.assert_called_once_with("mcp-setup_attempt", str(actor.id))
    publish.assert_not_called()
    if failure in ("denied", "permission", "stale"):
        exchange.assert_not_called()


def test_reused_grant_discovery_cannot_rotate_saved_refresh_token(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = setup_request.model_copy(update={"existing_server_id": 1})
    monkeypatch.setattr(
        api, "_prepare_mcp_setup", MagicMock(return_value=(request, "snapshot", None))
    )
    monkeypatch.setattr(
        api, "_mcp_setup_headers", MagicMock(return_value={"authorization": "stale"})
    )
    saved_grant = {
        "headers": {},
        "tokens": {"access_token": "usable", "refresh_token": "keep"},
    }
    monkeypatch.setattr(
        api, "_reusable_mcp_setup_grant", MagicMock(return_value=saved_grant)
    )
    start = AsyncMock()
    monkeypatch.setattr(api, "start_setup_oauth", start)
    discovery = MagicMock(side_effect=ValueError("unavailable"))
    monkeypatch.setattr(api, "discover_mcp_tools", discovery)
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(api.setup_mcp_server(request, MagicMock(), actor))
    assert discovery.call_args.args[1] == {"Authorization": "Bearer usable"}
    assert discovery.call_args.args[3] is None
    assert saved_grant["tokens"]["refresh_token"] == "keep"
    start.assert_not_called()
    publish.assert_not_called()


def test_sse_callback_discovery_uses_exchanged_bearer(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.shared.auth import OAuthToken

    from onyx.db.enums import MCPTransport
    from onyx.server.features.mcp.setup_oauth import TransientTokenStorage

    request = setup_request.model_copy(update={"transport": MCPTransport.SSE})
    monkeypatch.setattr(
        api, "_mcp_setup_headers", MagicMock(return_value={"authorization": "stale"})
    )
    attempt = MagicMock(request=request, expected_configuration_fingerprint=None)
    storage = TransientTokenStorage()
    asyncio.run(
        storage.set_tokens(OAuthToken(access_token="exchanged", token_type="Bearer"))
    )
    monkeypatch.setattr(api, "consume_setup_oauth", MagicMock(return_value=attempt))
    monkeypatch.setattr(api, "_assert_mcp_setup_current", MagicMock())
    monkeypatch.setattr(
        api, "complete_setup_oauth", AsyncMock(return_value=(MagicMock(), storage))
    )
    discovery = MagicMock(side_effect=ValueError("unavailable"))
    monkeypatch.setattr(api, "discover_mcp_tools", discovery)
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(
            api._complete_mcp_setup(
                {"state": "state", "code": "code"}, MagicMock(), actor
            )
        )
    assert discovery.call_args.args[1] == {"Authorization": "Bearer exchanged"}
    assert discovery.call_args.args[2] == MCPTransport.SSE
    publish.assert_not_called()


def test_fingerprinting_does_not_mutate_decrypted_credentials(
    actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from copy import deepcopy

    from onyx.server.features.mcp.models import MCPConnectionData

    raw: MCPConnectionData = {
        "headers": {"Authorization": "Bearer keep", "X-Tenant": "tenant"},
        "tokens": {"access_token": "keep", "refresh_token": "refresh"},
        "token_expires_at": 1234,
        "metadata": {"issuer": "https://provider.example"},
    }
    original = deepcopy(raw)
    server = MagicMock(auth_type=MCPAuthenticationType.OAUTH, id=1)
    server.user_groups = []
    server.users = []
    for name in ("get_connection_config_by_id", "get_user_connection_config"):
        monkeypatch.setattr(api, name, MagicMock())
    monkeypatch.setattr(api, "extract_connection_data", MagicMock(return_value=raw))
    monkeypatch.setattr(api, "get_default_assistant", MagicMock(return_value=None))
    monkeypatch.setattr(
        api, "get_workspace_action_policies", MagicMock(return_value={})
    )
    monkeypatch.setattr(api, "users_can_manage_policies", MagicMock(return_value=False))
    fingerprint = MagicMock(return_value="fingerprint")
    monkeypatch.setattr(api, "canonical_json_fingerprint", fingerprint)
    assert (
        api._mcp_setup_configuration_fingerprint(server, actor, MagicMock())
        == "fingerprint"
    )
    assert raw == original
    data = fingerprint.call_args.args[0]
    assert "tokens" not in data["user_data"]
    assert data["user_data"]["headers"] == {"X-Tenant": "tenant"}


@pytest.mark.parametrize("callback", [False, True])
def test_rejected_setup_credentials_are_unauthenticated(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    callback: bool,
) -> None:
    from onyx.error_handling.error_codes import OnyxErrorCode

    monkeypatch.setattr(
        api,
        "discover_mcp_tools",
        MagicMock(side_effect=api.MCPReauthenticationRequired()),
    )
    if callback:
        monkeypatch.setattr(
            api,
            "consume_setup_oauth",
            MagicMock(
                return_value=MagicMock(
                    request=setup_request, expected_configuration_fingerprint=None
                )
            ),
        )
        monkeypatch.setattr(api, "_assert_mcp_setup_current", MagicMock())
        monkeypatch.setattr(
            api,
            "complete_setup_oauth",
            AsyncMock(return_value=(MagicMock(), MagicMock(tokens=None))),
        )
        operation = api._complete_mcp_setup(
            {"state": "state", "code": "code"}, MagicMock(), actor
        )
    else:
        request = setup_request.model_copy(
            update={"auth_type": MCPAuthenticationType.NONE}
        )
        operation = api.setup_mcp_server(request, MagicMock(), actor)
    with pytest.raises(OnyxError) as error:
        asyncio.run(operation)
    assert error.value.error_code == OnyxErrorCode.UNAUTHENTICATED
    publish.assert_not_called()


def test_publication_locks_shared_settings_before_fingerprint(
    setup_request: MCPSetupRequest,
    actor: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        api, "get_mcp_server_by_id", MagicMock(return_value=MagicMock(id=1))
    )
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", MagicMock())

    def lock_policies(*_args: object, **kwargs: object) -> int:
        assert kwargs["for_update"] is True
        events.append("policy")
        return 1

    def lock_chat(*_args: object) -> None:
        events.append("chat")

    def fingerprint(*_args: object) -> str:
        events.append("fingerprint")
        return "saved"

    monkeypatch.setattr(api, "get_or_create_gated_app_id", lock_policies)
    monkeypatch.setattr(api, "lock_default_assistant__no_commit", lock_chat)
    monkeypatch.setattr(api, "_mcp_setup_configuration_fingerprint", fingerprint)
    api._assert_mcp_setup_current(
        setup_request.model_copy(update={"existing_server_id": 1}),
        actor,
        MagicMock(),
        "saved",
        for_update=True,
    )
    assert events == ["policy", "chat", "fingerprint"]


@pytest.mark.parametrize("callback", [False, True])
def test_publication_finishes_on_worker_before_success(
    setup_request: MCPSetupRequest,
    actor: User,
    publish: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    callback: bool,
) -> None:
    from threading import get_ident

    from onyx.db.enums import MCPServerStatus
    from onyx.server.features.mcp.models import MCPServer

    event_loop_thread = get_ident()
    completed = False
    server = MCPServer(
        id=123,
        name=setup_request.name,
        server_url=setup_request.server_url,
        owner=actor.email,
        connection_status=None,
        status=MCPServerStatus.CONNECTED,
    )

    def save(*_args: object, **_kwargs: object) -> MCPServer:
        nonlocal completed
        assert get_ident() != event_loop_thread
        completed = True
        return server

    publish.side_effect = save
    monkeypatch.setattr(api, "discover_mcp_tools", MagicMock(return_value=[]))
    if callback:
        monkeypatch.setattr(
            api,
            "consume_setup_oauth",
            MagicMock(
                return_value=MagicMock(
                    request=setup_request, expected_configuration_fingerprint=None
                )
            ),
        )
        monkeypatch.setattr(api, "_assert_mcp_setup_current", MagicMock())
        storage = MagicMock(tokens=None)
        storage.connection_data.return_value = {"headers": {}}
        monkeypatch.setattr(
            api, "complete_setup_oauth", AsyncMock(return_value=(MagicMock(), storage))
        )
        result = asyncio.run(
            api._complete_mcp_setup(
                {"state": "state", "code": "code"}, MagicMock(), actor
            )
        )
        assert result.server_id == server.id
    else:
        request = setup_request.model_copy(
            update={"auth_type": MCPAuthenticationType.NONE}
        )
        result = asyncio.run(api.setup_mcp_server(request, MagicMock(), actor))
        assert result.status == "connected"
        assert result.server.id == server.id
    assert completed
    publish.assert_called_once()
