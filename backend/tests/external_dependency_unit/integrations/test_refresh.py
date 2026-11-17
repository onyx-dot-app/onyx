"""ensure_fresh_connection: one call per connection, temporary and permanent
errors, and each token endpoint source."""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy.orm import Session

from onyx.auth import oauth_refresher
from onyx.auth.oauth_refresher import onyx_login_refresh_lock_name
from onyx.cache.locks import cache_shared_lock
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import get_integration_by_id
from onyx.db.integration_connection import (
    delete_connection__no_commit,
    get_connection_by_id,
    upsert_connection__no_commit,
)
from onyx.db.models import Integration, OAuthAccount, User
from onyx.integrations.connection_models import (
    OAUTH_CLIENT_INFO_KEY,
    OAUTH_METADATA_KEY,
    ConnectionSecret,
    ConnectionState,
    read_connection_secret,
)
from onyx.integrations.connections import (
    ConnectionProblem,
    ensure_fresh_connection,
    mark_sign_in_settings_changed,
    resolve_connection,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    make_app_integration,
    make_mcp_integration,
)
from tests.external_dependency_unit.integrations.conftest import (
    TOKEN_URL,
    FakeTokenEndpoint,
    add_connection,
    expired,
    far_future,
    new_oauth_client,
    token_response,
)

logger = setup_logger()


def _manual_integration(db_session: Session) -> Integration:
    return make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="client",
            client_secret="secret",
        ),
    )[0]


def _stale_secret() -> ConnectionSecret:
    return ConnectionSecret(
        access_token="old-access", refresh_token="old-refresh", token_type="Bearer"
    )


def test_two_concurrent_refreshes_make_one_call(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("concurrent_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.delay_s = 0.5
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    results: list[str | None] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2, timeout=30)

    def refresh() -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            with get_session_with_current_tenant() as session:
                own_connection = get_connection_by_id(session, connection.id)
                own_integration = get_integration_by_id(integration.id, session)
                assert own_connection is not None and own_integration is not None
                start.wait()
                fresh = ensure_fresh_connection(
                    own_connection, own_integration, session
                )
                assert fresh is not None
                results.append(read_connection_secret(fresh).access_token)
        except BaseException as error:
            errors.append(error)
            # A blocked peer raises BrokenBarrierError instead of hanging.
            start.abort()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    threads = [threading.Thread(target=refresh) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors
    assert len(token_endpoint.requests) == 1
    assert results == ["new-access", "new-access"]
    body = parse_qs(token_endpoint.requests[0].content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["old-refresh"]
    assert body["client_id"] == ["client"]
    assert str(token_endpoint.requests[0].url) == TOKEN_URL

    db_session.refresh(connection)
    secret = read_connection_secret(connection)
    assert secret.refresh_token == "new-refresh"
    assert connection.expires_at is not None and connection.expires_at > expired()


def _sign_in_during_refresh(
    integration: Integration, user: User, token_endpoint: FakeTokenEndpoint
) -> Callable[..., httpx.Response]:
    """A token endpoint that lets an OAuth callback store a new grant while
    the refresh waits for the response."""

    def send(request: httpx.Request, *, mcp: bool) -> httpx.Response:
        with get_session_with_current_tenant() as session:
            upsert_connection__no_commit(
                session,
                integration_id=integration.id,
                user_id=user.id,
                secret=ConnectionSecret(
                    access_token="callback-access", refresh_token="callback-refresh"
                ).model_dump(mode="json"),
                expires_at=far_future(),
                granted_scopes=None,
            )
            session.commit()
        return token_endpoint.send(request, mcp=mcp)

    return send


@pytest.mark.parametrize("status_code", [200, 400], ids=["refreshed", "refused"])
def test_refresh_result_does_not_replace_a_newer_sign_in(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
    status_code: int,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("refresh_race")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = status_code
    if status_code != 200:
        token_endpoint.body = {"error": "invalid_grant"}

    with patch(
        "onyx.integrations.connections._send_token_request",
        _sign_in_during_refresh(integration, user, token_endpoint),
    ):
        ensure_fresh_connection(connection, integration, db_session)

    assert len(token_endpoint.requests) == 1
    db_session.expire_all()
    kept = get_connection_by_id(db_session, connection.id)
    assert kept is not None
    assert kept.status is IntegrationConnectionStatus.CONNECTED
    assert read_connection_secret(kept).access_token == "callback-access"


def test_refresh_result_does_not_undo_a_sign_in_settings_change(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("refresh_settings_change")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )

    def send(request: httpx.Request, *, mcp: bool) -> httpx.Response:
        with get_session_with_current_tenant() as session:
            mark_sign_in_settings_changed(integration.id, session)
            session.commit()
        return token_endpoint.send(request, mcp=mcp)

    with patch("onyx.integrations.connections._send_token_request", send):
        ensure_fresh_connection(connection, integration, db_session)

    assert len(token_endpoint.requests) == 1
    db_session.expire_all()
    kept = get_connection_by_id(db_session, connection.id)
    assert kept is not None
    assert kept.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert read_connection_secret(kept).access_token == "old-access"


@pytest.mark.parametrize("status_code", [200, 400], ids=["refreshed", "refused"])
def test_refresh_does_not_commit_or_discard_the_work_of_the_caller(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
    status_code: int,
) -> None:
    integration = _manual_integration(db_session)
    name = integration.name
    user = make_test_user("refresh_caller_session")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = status_code
    if status_code != 200:
        token_endpoint.body = {"error": "invalid_grant"}
    integration.name = f"{name} renamed"

    fresh = ensure_fresh_connection(connection, integration, db_session)

    assert fresh is not None
    if status_code == 200:
        assert read_connection_secret(fresh).access_token == "new-access"
    else:
        assert fresh.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert integration.name == f"{name} renamed"
    db_session.rollback()
    assert integration.name == name


def test_fresh_token_makes_no_call(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("fresh_token")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=far_future()
    )
    ensure_fresh_connection(connection, integration, db_session)
    assert token_endpoint.requests == []


def test_dead_refresh_token_needs_reconnect_and_keeps_row(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("dead_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 400
    token_endpoint.body = {"error": "invalid_grant"}

    result = resolve_connection(integration, user, db_session)

    assert isinstance(result, ConnectionProblem)
    assert result.code is ConnectionState.NEEDS_RECONNECT
    assert "invalid_grant" in result.reason
    kept = get_connection_by_id(db_session, connection.id)
    assert kept is not None
    assert kept.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert kept.status_reason == result.reason
    assert read_connection_secret(kept).refresh_token == "old-refresh"

    # A row that needs reconnect is not refreshed again.
    resolve_connection(integration, user, db_session)
    assert len(token_endpoint.requests) == 1


def test_temporary_error_keeps_token(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("temporary_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 503
    token_endpoint.body = {"error": "temporarily_unavailable"}

    ensure_fresh_connection(connection, integration, db_session)

    db_session.refresh(connection)
    assert connection.status is IntegrationConnectionStatus.CONNECTED
    assert read_connection_secret(connection).access_token == "old-access"
    assert len(token_endpoint.requests) == 1


def test_client_error_keeps_the_connection_connected(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("invalid_client_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 401
    token_endpoint.body = {"error": "invalid_client"}

    ensure_fresh_connection(connection, integration, db_session)

    db_session.refresh(connection)
    assert connection.status is IntegrationConnectionStatus.CONNECTED
    assert len(token_endpoint.requests) == 1


def test_connection_deleted_during_the_lock_wait_is_not_connected(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("deleted_during_refresh")
    add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )

    @contextmanager
    def lock_after_a_disconnect(*_: object, **__: object) -> Iterator[None]:
        with get_session_with_current_tenant() as other_session:
            delete_connection__no_commit(other_session, integration.id, user.id)
            other_session.commit()
        yield

    with patch(
        "onyx.integrations.connections.cache_shared_lock", lock_after_a_disconnect
    ):
        result = resolve_connection(integration, user, db_session)

    assert isinstance(result, ConnectionProblem)
    assert result.code is ConnectionState.NOT_CONNECTED
    assert token_endpoint.requests == []


@pytest.mark.parametrize("status_code", [200, 400], ids=["refreshed", "refused"])
def test_connection_deleted_during_the_token_request_is_not_connected(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
    status_code: int,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("deleted_during_token_request")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = status_code
    if status_code != 200:
        token_endpoint.body = {"error": "invalid_grant"}

    def send(request: httpx.Request, *, mcp: bool) -> httpx.Response:
        with get_session_with_current_tenant() as other_session:
            delete_connection__no_commit(other_session, integration.id, user.id)
            other_session.commit()
        return token_endpoint.send(request, mcp=mcp)

    with patch("onyx.integrations.connections._send_token_request", send):
        assert ensure_fresh_connection(connection, integration, db_session) is None
        result = resolve_connection(integration, user, db_session)

    assert isinstance(result, ConnectionProblem)
    assert result.code is ConnectionState.NOT_CONNECTED


def test_expired_token_after_a_temporary_refresh_error_is_not_used(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("expired_after_temporary_error")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 503
    token_endpoint.body = {"error": "temporarily_unavailable"}

    result = resolve_connection(integration, user, db_session)

    assert isinstance(result, ConnectionProblem)
    assert result.code is ConnectionState.NEEDS_RECONNECT
    db_session.refresh(connection)
    # The row stays connected, so the next call tries the refresh again.
    assert connection.status is IntegrationConnectionStatus.CONNECTED
    resolve_connection(integration, user, db_session)
    assert len(token_endpoint.requests) == 2


def test_expired_token_without_refresh_token_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(db_session)
    user = make_test_user("no_refresh_token")
    connection = add_connection(
        db_session,
        integration,
        user.id,
        ConnectionSecret(access_token="old"),
        expires_at=expired(),
    )
    ensure_fresh_connection(connection, integration, db_session)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert token_endpoint.requests == []


def test_preset_refresh_uses_provider(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        app_type=ExternalAppType.LINEAR,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            client_id="linear-client",
            client_secret="linear-secret",
        ),
    )
    user = make_test_user("preset_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    post = MagicMock(
        return_value=token_response(
            {
                "access_token": "linear-new",
                "refresh_token": "linear-refresh-2",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )
    with patch.object(requests, "post", post):
        ensure_fresh_connection(connection, integration, db_session)
    assert post.call_count == 1
    assert post.call_args.kwargs["data"]["client_id"] == "linear-client"
    secret = read_connection_secret(connection)
    assert secret.access_token == "linear-new"
    assert secret.refresh_token == "linear-refresh-2"

    connection.expires_at = expired()
    db_session.commit()
    with patch.object(
        requests,
        "post",
        MagicMock(return_value=token_response({"error": "invalid_grant"}, 400)),
    ):
        ensure_fresh_connection(connection, integration, db_session)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT


def test_preset_refresh_with_a_bad_expires_in_has_no_expiry(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        app_type=ExternalAppType.LINEAR,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            client_id="linear-client",
            client_secret="linear-secret",
        ),
    )
    user = make_test_user("preset_bad_expiry")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    post = MagicMock(
        return_value=token_response(
            {"access_token": "linear-new", "token_type": "Bearer", "expires_in": "soon"}
        )
    )
    with patch.object(requests, "post", post):
        ensure_fresh_connection(connection, integration, db_session)
    assert read_connection_secret(connection).access_token == "linear-new"
    assert connection.expires_at is None


_SDK_TOKEN_URL = "https://mcp-auth.example.test/oauth/token"


def _discovery_mcp_integration(db_session: Session) -> Integration:
    return make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.DISCOVERY,
            client_id="dcr-client",
            registration={
                OAUTH_CLIENT_INFO_KEY: {
                    "client_id": "dcr-client",
                    "redirect_uris": ["https://onyx.example.test/mcp/oauth/callback"],
                    "token_endpoint_auth_method": "none",
                },
                OAUTH_METADATA_KEY: {
                    "issuer": "https://mcp-auth.example.test",
                    "authorization_endpoint": "https://mcp-auth.example.test/authorize",
                    "token_endpoint": _SDK_TOKEN_URL,
                },
            },
        ),
    )[0]


def test_mcp_refresh_uses_sdk_request(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _discovery_mcp_integration(db_session)
    user: User = make_test_user("mcp_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    ensure_fresh_connection(connection, integration, db_session)

    assert len(token_endpoint.requests) == 1
    request = token_endpoint.requests[0]
    assert str(request.url) == _SDK_TOKEN_URL
    body = parse_qs(request.content.decode())
    assert body["refresh_token"] == ["old-refresh"]
    assert body["client_id"] == ["dcr-client"]
    assert read_connection_secret(connection).access_token == "new-access"


def test_mcp_refresh_reads_form_encoded_responses(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _discovery_mcp_integration(db_session)
    token_endpoint.form_encoded = True
    rotated = make_test_user("mcp_refresh_form")
    rotated_connection = add_connection(
        db_session, integration, rotated.id, _stale_secret(), expires_at=expired()
    )

    ensure_fresh_connection(rotated_connection, integration, db_session)

    secret = read_connection_secret(rotated_connection)
    assert (secret.access_token, secret.refresh_token) == ("new-access", "new-refresh")
    assert rotated_connection.expires_at is not None

    rejected = make_test_user("mcp_refresh_form_rejected")
    rejected_connection = add_connection(
        db_session, integration, rejected.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 400
    token_endpoint.body = {"error": "invalid_grant"}

    problem = resolve_connection(integration, rejected, db_session)

    assert isinstance(problem, ConnectionProblem)
    assert problem.code is ConnectionState.NEEDS_RECONNECT
    assert "invalid_grant" in problem.reason
    db_session.refresh(rejected_connection)
    assert rejected_connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT


def test_web_login_refresh_waits_for_the_shared_login_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The web refresher and the background refresher take one lock, so they
    do not redeem the same rotating refresh token at the same time."""
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "login-lock@example.com"
    account = MagicMock(spec=OAuthAccount)
    account.refresh_token = "login-refresh"
    account.expires_at = int(time.time())
    user.oauth_accounts = [account]
    db_session = MagicMock()
    db_session.refresh = AsyncMock()
    refresh = AsyncMock(return_value=True)
    monkeypatch.setattr(oauth_refresher, "refresh_oauth_token", refresh)
    monkeypatch.setattr(oauth_refresher, "reload_user_oidc_expiry", AsyncMock())
    monkeypatch.setattr(oauth_refresher, "LOGIN_REFRESH_LOCK_WAIT_S", 0.2)

    with cache_shared_lock(
        onyx_login_refresh_lock_name(user.id),
        max_time_lock_held_s=10,
        wait_for_lock_s=1,
        logger=logger,
    ):
        asyncio.run(
            oauth_refresher.check_and_refresh_oauth_tokens(
                user, db_session, MagicMock()
            )
        )
    refresh.assert_not_awaited()

    asyncio.run(
        oauth_refresher.check_and_refresh_oauth_tokens(user, db_session, MagicMock())
    )
    refresh.assert_awaited_once()
