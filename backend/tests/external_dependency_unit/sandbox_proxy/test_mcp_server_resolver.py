"""External-dependency-unit tests for `MCPServerResolver` against a real DB.

Pins the claim->resolve contract per MCP auth mode: craft-enabled servers are
claimed by exact URL-prefix attribution, credentials come from the same
`mcp_connection_config` rows chat writes, an expired OAuth token is refreshed
through the token endpoint and persisted back to the shared row, and missing
credentials fail closed with agent-facing prose naming the server.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheLockAcquisitionError
from onyx.db.enums import (
    EndpointPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.mcp import (
    create_connection_config,
    create_mcp_server__no_commit,
    extract_connection_data,
    get_connection_config_by_id,
    update_mcp_server__no_commit,
)
from onyx.db.models import MCPServer, OAuthAccount, User
from onyx.external_apps.matching.engine import (
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
)
from onyx.sandbox_proxy.credential_injection import (
    CredentialUnavailableError,
    InjectionContext,
)
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from onyx.server.features.mcp.models import MCPConnectionData, MCPOAuthKeys
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user

CraftServerFactory = Callable[..., MCPServer]


@pytest.fixture
def craft_server(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[CraftServerFactory, None, None]:
    """Factory for craft-enabled MCP servers, auto-deleted with their connection
    configs at teardown (via `mcp_server_id` cascade)."""
    created: list[MCPServer] = []

    def _make(
        *,
        auth_type: MCPAuthenticationType,
        auth_performer: MCPAuthenticationPerformer,
        host: str | None = None,
        path: str = "/mcp",
        available_in_craft: bool = True,
        oauth_provider_mode: MCPOAuthProviderMode = MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint: str | None = None,
        oauth_token_endpoint: str | None = None,
    ) -> MCPServer:
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=f"test-mcp-{uuid4().hex[:8]}",
            description=None,
            server_url=f"https://{host or _unique_host()}{path}",
            auth_type=auth_type,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=auth_performer,
            db_session=db_session,
            oauth_provider_mode=oauth_provider_mode,
            oauth_authorization_endpoint=oauth_authorization_endpoint,
            oauth_token_endpoint=oauth_token_endpoint,
        )
        update_mcp_server__no_commit(
            server_id=server.id,
            db_session=db_session,
            available_in_craft=available_in_craft,
        )
        db_session.commit()
        created.append(server)
        return server

    yield _make
    db_session.rollback()
    for server in created:
        db_session.delete(server)
    db_session.commit()


def _unique_host() -> str:
    return f"api-{uuid4().hex[:8]}.example.com"


def _server_host(server: MCPServer) -> str:
    return server.server_url.split("://", 1)[1].split("/", 1)[0]


def _attach_admin_config(
    db_session: Session, server: MCPServer, config_data: MCPConnectionData
) -> int:
    config = create_connection_config(config_data, db_session, mcp_server_id=server.id)
    update_mcp_server__no_commit(
        server_id=server.id,
        db_session=db_session,
        admin_connection_config_id=config.id,
    )
    db_session.commit()
    return config.id


def _attach_user_config(
    db_session: Session,
    server: MCPServer,
    user_email: str,
    config_data: MCPConnectionData,
) -> int:
    config = create_connection_config(
        config_data, db_session, mcp_server_id=server.id, user_email=user_email
    )
    db_session.commit()
    return config.id


def _matched(kind: GatedAppKind, target_id: int) -> AllMatchedActions:
    return AllMatchedActions(
        actions=(
            MatchedAction(
                action_type="x",
                display_name="X",
                description="d",
                policy=EndpointPolicy.ASK,
            ),
        ),
        target=GatedTarget(kind=kind, id=target_id, app_name="srv"),
    )


def _ctx(user: User) -> InjectionContext:
    return InjectionContext(
        sandbox=ResolvedSandbox(
            sandbox_id=uuid4(),
            user_id=user.id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA,
            sandbox_name="sandbox-test",
            sandbox_ip="127.0.0.1",
        ),
        matched_actions=None,
    )


def _request(
    host: str, path: str = "/mcp", port: int = 443, scheme: str = "https"
) -> MagicMock:
    return MagicMock(host=host, port=port, path=path, scheme=scheme)


def test_admin_api_token_injects_stored_headers(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_api_token")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    host = _server_host(server)
    _attach_admin_config(
        db_session,
        server,
        MCPConnectionData(headers={"Authorization": "Bearer admin-token"}),
    )

    resolver = MCPServerResolver()
    ctx = _ctx(user)
    assert resolver.claims(_request(host), ctx) is True
    assert resolver.claims(_request("unrelated.example.com"), ctx) is False
    assert resolver.resolve(_request(host), ctx) == {
        "Authorization": "Bearer admin-token"
    }


def test_per_user_missing_config_is_blocked_naming_server(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_missing")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
    )

    with pytest.raises(CredentialUnavailableError) as exc_info:
        MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    assert server.name in (exc_info.value.sandbox_detail or "")


def test_non_craft_enabled_server_is_not_claimed(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_disabled")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        available_in_craft=False,
    )

    assert (
        MCPServerResolver().claims(_request(_server_host(server)), _ctx(user)) is False
    )


def test_request_outside_server_url_prefix_is_blocked(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_prefix")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    host = _server_host(server)
    _attach_admin_config(
        db_session,
        server,
        MCPConnectionData(headers={"Authorization": "Bearer admin-token"}),
    )

    resolver = MCPServerResolver()
    ctx = _ctx(user)
    # The whole host is claimed...
    assert resolver.claims(_request(host, path="/other"), ctx) is True
    # ...but only the configured MCP endpoint resolves; siblings fail closed.
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(_request(host, path="/other"), ctx)
    assert resolver.resolve(_request(host, path="/mcp"), ctx) != {}
    assert resolver.resolve(_request(host, path="/mcp/session"), ctx) != {}


@pytest.mark.parametrize(
    "attack_path",
    ["/mcp/../admin", "/mcp/%2e%2e/admin", "/mcp/subtool/../../secret"],
)
def test_path_traversal_is_blocked(
    db_session: Session, craft_server: CraftServerFactory, attack_path: str
) -> None:
    """A path that normalizes outside the configured prefix must not get creds,
    even though its raw form is prefixed by the server_url path."""
    user = create_test_user(db_session, "mcp_resolver_traversal")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session,
        server,
        MCPConnectionData(headers={"Authorization": "Bearer admin-token"}),
    )

    with pytest.raises(CredentialUnavailableError):
        MCPServerResolver().resolve(
            _request(_server_host(server), path=attack_path), _ctx(user)
        )


def test_plaintext_request_to_https_server_is_not_claimed(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """An https server's bearer must never be injected onto a plaintext http
    request to the same host:port."""
    user = create_test_user(db_session, "mcp_resolver_scheme")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    host = _server_host(server)
    _attach_admin_config(
        db_session, server, MCPConnectionData(headers={"Authorization": "Bearer x"})
    )

    resolver = MCPServerResolver()
    ctx = _ctx(user)
    assert resolver.claims(_request(host, scheme="https"), ctx) is True
    assert resolver.claims(_request(host, port=443, scheme="http"), ctx) is False


def test_longest_prefix_wins_when_servers_share_a_host(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """Two craft servers on one host: a request under the more specific prefix
    gets that server's credentials, not the broader one's."""
    user = create_test_user(db_session, "mcp_resolver_prefix_tie")
    host = _unique_host()
    broad = craft_server(
        host=host,
        path="/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session, broad, MCPConnectionData(headers={"Authorization": "Bearer broad"})
    )
    specific = craft_server(
        host=host,
        path="/mcp/v2",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session,
        specific,
        MCPConnectionData(headers={"Authorization": "Bearer specific"}),
    )

    resolver = MCPServerResolver()
    assert resolver.resolve(_request(host, path="/mcp/v2/call"), _ctx(user)) == {
        "Authorization": "Bearer specific"
    }
    assert resolver.resolve(_request(host, path="/mcp/call"), _ctx(user)) == {
        "Authorization": "Bearer broad"
    }


def test_duplicate_endpoint_attribution_fails_closed(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """Two craft servers with the same URL claim the same endpoint with no way
    to tell which owns the request — resolve must fail closed rather than inject
    an arbitrary config's credentials."""
    user = create_test_user(db_session, "mcp_resolver_dup")
    host = _unique_host()
    first = craft_server(
        host=host,
        path="/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session, first, MCPConnectionData(headers={"Authorization": "Bearer first"})
    )
    second = craft_server(
        host=host,
        path="/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session,
        second,
        MCPConnectionData(headers={"Authorization": "Bearer second"}),
    )

    with pytest.raises(CredentialUnavailableError) as exc_info:
        MCPServerResolver().resolve(_request(host, path="/mcp/call"), _ctx(user))
    assert "ambiguous" in str(exc_info.value)


def test_flag_flipped_since_cache_is_blocked(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """A server cached as craft-enabled but disabled since is blocked on the
    resolve() re-read, not served from the stale claims() cache."""
    user = create_test_user(db_session, "mcp_resolver_flipped")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    host = _server_host(server)
    _attach_admin_config(
        db_session, server, MCPConnectionData(headers={"Authorization": "Bearer x"})
    )

    resolver = MCPServerResolver()
    # Warm the target cache while the server is still enabled.
    assert resolver.claims(_request(host), _ctx(user)) is True
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=False
    )
    db_session.commit()
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(_request(host), _ctx(user))


def test_matched_request_claim_depends_on_target_kind(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """A request the external-app matcher attributed belongs to that resolver,
    even on a shared host — MCP defers. But an MCP `tools/call` the evaluator
    gated is still MCP's to inject onto."""
    user = create_test_user(db_session, "mcp_resolver_matched")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    host = _server_host(server)

    resolver = MCPServerResolver()
    ctx = _ctx(user)
    assert resolver.claims(_request(host), ctx) is True

    external_ctx = InjectionContext(
        sandbox=ctx.sandbox, matched_actions=_matched(GatedAppKind.EXTERNAL_APP, 99)
    )
    assert resolver.claims(_request(host), external_ctx) is False

    mcp_ctx = InjectionContext(
        sandbox=ctx.sandbox,
        matched_actions=_matched(GatedAppKind.MCP_SERVER, server.id),
    )
    assert resolver.claims(_request(host), mcp_ctx) is True


def test_admin_managed_server_detail_points_to_admin(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """An admin-performer server with no config tells the agent to reach an
    admin, not to connect it from the user's Apps page."""
    user = create_test_user(db_session, "mcp_resolver_admin_copy")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )

    with pytest.raises(CredentialUnavailableError) as exc_info:
        MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    detail = exc_info.value.sandbox_detail or ""
    assert "admin" in detail.lower()
    assert "Apps page in Craft" not in detail


def test_none_auth_claims_without_injecting(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_none")
    server = craft_server(
        auth_type=MCPAuthenticationType.NONE,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )

    assert MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user)) == {}


def test_pt_oauth_injects_user_login_token(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_resolver_pt")
    db_session.add(
        OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id=f"acct-{uuid4().hex[:8]}",
            account_email=user.email,
            access_token="login-oauth-token",
            refresh_token="",
        )
    )
    db_session.commit()
    db_session.refresh(user)

    server = craft_server(
        auth_type=MCPAuthenticationType.PT_OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
    )

    headers = MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    assert headers == {"Authorization": "Bearer login-oauth-token"}


def test_valid_oauth_token_injected_without_refresh(
    db_session: Session,
    craft_server: CraftServerFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "mcp_resolver_oauth_ok")
    server = craft_server(
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
    )
    _attach_user_config(
        db_session,
        server,
        user.email,
        MCPConnectionData(
            headers={"Authorization": "Bearer current-token"},
            tokens={
                "access_token": "current-token",
                "token_type": "Bearer",
                "refresh_token": "rt-1",
            },
            token_expires_at=time.time() + 3600,
        ),
    )

    def _fail_refresh(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("refresh must not run for an unexpired token")

    monkeypatch.setattr(
        "onyx.sandbox_proxy.resolvers.mcp_server.refresh_mcp_oauth_token_if_expired",
        _fail_refresh,
    )

    headers = MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    assert headers == {"Authorization": "Bearer current-token"}


def _mock_token_endpoint(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Swap the SSRF-guarded httpx factory the shared refresh primitive uses for
    one whose transport answers the token-refresh POST locally, 404ing the rest."""

    def _handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return respond(request)
        return httpx.Response(404)

    def _factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,  # noqa: ARG001
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_handle), headers=headers, auth=auth
        )

    monkeypatch.setattr(
        "onyx.server.features.mcp.oauth.mcp_ssrf_httpx_client_factory", _factory
    )


_CLIENT_INFO = {
    "client_id": "cid",
    "client_secret": "csecret",
    "redirect_uris": ["https://app.example.com/mcp/oauth/callback"],
}


def _expired_oauth_config(refresh_token: str) -> MCPConnectionData:
    return MCPConnectionData(
        headers={"Authorization": "Bearer stale-token"},
        tokens={
            "access_token": "stale-token",
            "token_type": "Bearer",
            "refresh_token": refresh_token,
        },
        client_info=_CLIENT_INFO,
        token_expires_at=time.time() - 60,
    )


def test_expired_oauth_token_refreshed_and_persisted(
    db_session: Session,
    craft_server: CraftServerFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "mcp_resolver_oauth_refresh")
    auth_host = f"auth-{uuid4().hex[:8]}.example.com"
    token_endpoint = f"https://{auth_host}/token"
    # KNOWN_PROVIDER so make_oauth_provider hydrates the SDK with the real token
    # endpoint — the same path chat's per-tool-call refresh exercises.
    server = craft_server(
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
        oauth_authorization_endpoint=f"https://{auth_host}/authorize",
        oauth_token_endpoint=token_endpoint,
    )
    config_id = _attach_user_config(
        db_session, server, user.email, _expired_oauth_config("rt-1")
    )

    posted: dict[str, Any] = {}

    def _respond(request: httpx.Request) -> httpx.Response:
        posted["url"] = str(request.url)
        posted["data"] = dict(parse_qsl(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rt-2",
            },
        )

    _mock_token_endpoint(monkeypatch, _respond)

    headers = MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    assert headers == {"Authorization": "Bearer fresh-token"}
    assert posted["url"] == token_endpoint
    assert posted["data"]["grant_type"] == "refresh_token"
    assert posted["data"]["refresh_token"] == "rt-1"

    # The refresh persisted to the shared row chat reads.
    db_session.expire_all()
    config_data = extract_connection_data(
        get_connection_config_by_id(config_id, db_session), apply_mask=False
    )
    assert config_data["headers"] == {"Authorization": "Bearer fresh-token"}
    assert config_data[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "rt-2"
    assert config_data[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] > time.time()


def test_expired_oauth_token_unrefreshable_is_blocked(
    db_session: Session,
    craft_server: CraftServerFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_test_user(db_session, "mcp_resolver_oauth_dead")
    auth_host = f"auth-{uuid4().hex[:8]}.example.com"
    server = craft_server(
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
        oauth_authorization_endpoint=f"https://{auth_host}/authorize",
        oauth_token_endpoint=f"https://{auth_host}/token",
    )
    _attach_user_config(
        db_session, server, user.email, _expired_oauth_config("rt-dead")
    )

    _mock_token_endpoint(
        monkeypatch,
        lambda _request: httpx.Response(400, json={"error": "invalid_grant"}),
    )

    with pytest.raises(CredentialUnavailableError) as exc_info:
        MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    assert server.name in (exc_info.value.sandbox_detail or "")


def test_refresh_lock_contention_yields_retry_detail(
    db_session: Session,
    craft_server: CraftServerFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the shared single-flight lock is held by another refresher and the
    token hasn't been refreshed yet, the agent is told to retry, not just to
    reconnect a server that may be fine."""
    user = create_test_user(db_session, "mcp_resolver_contended")
    server = craft_server(
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_token_endpoint=f"https://auth-{uuid4().hex[:8]}.example.com/token",
    )
    _attach_user_config(db_session, server, user.email, _expired_oauth_config("rt-1"))

    def _contended(*_args: Any, **_kwargs: Any) -> Any:
        raise CacheLockAcquisitionError("held by another refresher")

    monkeypatch.setattr("onyx.server.features.mcp.oauth.cache_shared_lock", _contended)

    with pytest.raises(CredentialUnavailableError) as exc_info:
        MCPServerResolver().resolve(_request(_server_host(server)), _ctx(user))
    detail = exc_info.value.sandbox_detail or ""
    assert "retry" in detail.lower()
    assert server.name in detail


def test_gated_request_injects_for_the_evaluated_server(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """When the gate attributed the request (``matched_actions`` carries an MCP
    target), injection uses that server id directly — never a re-match against
    the resolver's cached targets, which can be stale after a URL change."""
    user = create_test_user(db_session, "mcp_resolver_attr")
    server = craft_server(
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
    )
    _attach_admin_config(
        db_session,
        server,
        MCPConnectionData(headers={"Authorization": "Bearer admin-token"}),
    )
    host = _server_host(server)

    resolver = MCPServerResolver()
    ctx = InjectionContext(
        sandbox=_ctx(user).sandbox,
        matched_actions=_matched(GatedAppKind.MCP_SERVER, server.id),
    )
    # A path the resolver's own matching would fail closed on still resolves,
    # because the gate's attribution wins for gated requests.
    assert resolver.resolve(_request(host, path="/other"), ctx) == {
        "Authorization": "Bearer admin-token"
    }
