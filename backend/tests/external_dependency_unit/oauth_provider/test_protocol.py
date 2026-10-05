import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi_users.jwt import generate_jwt
from fastmcp.server.auth import cimd
from fastmcp.server.auth.ssrf import SSRFFetchError, SSRFFetchResponse
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.pkce import generate_pkce_pair
from onyx.auth.schemas import AuthBackend
from onyx.auth.users import (
    SingleTenantJWTStrategy,
    TenantAwareRedisStrategy,
    auth_backend,
    fastapi_users,
    get_redis_strategy,
)
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.async_sql_engine import reset_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.enums import Permission
from onyx.db.models import OAuthProviderClient, OAuthProviderGrant, User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.mcp_oauth import auth as oauth_auth
from onyx.mcp_oauth.config import get_mcp_oauth_settings
from onyx.server.auth_check import check_router_auth
from onyx.server.mcp_oauth import api as oauth_api
from onyx.server.mcp_oauth import provider as oauth_provider
from onyx.server.mcp_oauth.api import router as user_router
from onyx.server.mcp_oauth.protocol import create_mcp_oauth_protocol_router
from onyx.server.mcp_oauth.provider import _cimd_fetcher
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.usefixtures("tenant_context"),
]
_ORIGIN = "http://localhost:3000"
_RESOURCE = f"{_ORIGIN}/mcp/"
_REDIRECT = "http://127.0.0.1:9876/callback"


@pytest.fixture(params=[AuthBackend.REDIS])
def protocol_session_strategy(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> TenantAwareRedisStrategy | SingleTenantJWTStrategy:
    backend = request.param
    monkeypatch.setattr(app_configs, "AUTH_BACKEND", backend)
    if backend == AuthBackend.JWT:
        strategy = SingleTenantJWTStrategy(
            secret="mcp-protocol-jwt-test-secret-longer-than-32-bytes",
            lifetime_seconds=3600,
        )
        monkeypatch.setattr(oauth_api, "get_jwt_strategy", lambda: strategy)
        return strategy
    return get_redis_strategy()


@pytest_asyncio.fixture(loop_scope="module")
async def protocol_client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    redis_client: Redis,
    protocol_session_strategy: TenantAwareRedisStrategy | SingleTenantJWTStrategy,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", True)
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", _ORIGIN)
    user = create_test_user(db_session, "mcp_protocol", assign_default_group=False)
    user.effective_permissions = [
        Permission.READ_SEARCH.value,
        Permission.CREATE_USER_API_KEYS.value,
    ]
    db_session.commit()
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(create_mcp_oauth_protocol_router(get_mcp_oauth_settings()))
    app.include_router(user_router)
    app.include_router(
        fastapi_users.get_refresh_router(auth_backend, requires_verification=False),
        prefix="/auth",
    )
    app.dependency_overrides[auth_backend.get_strategy] = lambda: (
        protocol_session_strategy
    )

    @app.post("/search")
    def search(
        user: User = Depends(require_permission(Permission.READ_SEARCH)),
    ) -> dict[str, str]:
        return {"user_id": str(user.id)}

    @app.get("/unrelated")
    def unrelated(
        user: User = Depends(require_permission(Permission.READ_SEARCH)),
    ) -> dict[str, str]:
        return {"user_id": str(user.id)}

    check_router_auth(app)
    strategy = protocol_session_strategy
    session_token = await strategy.write_token(user)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app, client=(f"protocol-{uuid4().hex}", 1234)),
        base_url=_ORIGIN,
        cookies={FASTAPI_USERS_AUTH_COOKIE_NAME: session_token},
        headers={"X-Mcp-Test-Owner": str(user.id)},
    ) as client:
        try:
            yield client
        finally:
            await strategy.destroy_token(session_token, user)
            if isinstance(strategy, TenantAwareRedisStrategy):
                await redis_client.delete(f"{strategy.key_prefix}{session_token}")
            db_session.rollback()
            db_session.execute(
                delete(OAuthProviderGrant).where(OAuthProviderGrant.user_id == user.id)
            )
            delete_test_user(db_session, user)
            db_session.commit()
            with get_catalog_session() as catalog:
                clients = catalog.scalars(
                    select(OAuthProviderClient).where(
                        OAuthProviderClient.client_metadata["client_name"].astext
                        == str(user.id)
                    )
                ).all()
                for registered in clients:
                    catalog.delete(registered)
                catalog.commit()
            await reset_sqlalchemy_async_engine()


async def _register(client: httpx.AsyncClient) -> str:
    # The random name isolates registry cleanup from other concurrently running tests.
    name = client.headers["X-Mcp-Test-Owner"]
    response = await client.post(
        "/mcp-oauth/register",
        json={
            "client_name": name,
            "redirect_uris": [_REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in payload
    client_id: str = payload["client_id"]
    return client_id


async def _begin_authorization(
    client: httpx.AsyncClient, client_id: str
) -> tuple[str, str]:
    verifier, challenge = generate_pkce_pair()
    response = await client.get(
        "/mcp-oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": _REDIRECT,
            "response_type": "code",
            "scope": "read:search",
            "resource": _RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
        },
    )
    assert response.status_code == 302, response.text
    handle = parse_qs(urlsplit(response.headers["location"]).query)["request"][0]
    return handle, verifier


async def _authorize(client: httpx.AsyncClient, client_id: str) -> tuple[str, str]:
    handle, verifier = await _begin_authorization(client, client_id)
    details = await client.get("/mcp-oauth/consent", params={"request": handle})
    assert details.status_code == 200, details.text
    approval = await client.post(
        "/mcp-oauth/consent",
        headers={"Origin": _ORIGIN},
        json={
            "request_id": handle,
            "csrf_token": details.json()["csrf_token"],
            "decision": "allow",
        },
    )
    assert approval.status_code == 200, approval.text
    redirect = parse_qs(urlsplit(approval.json()["redirect_url"]).query)
    assert redirect["state"] == ["client-state"]
    assert redirect["iss"] == [f"{_ORIGIN}/api/mcp-oauth"]
    return redirect["code"][0], verifier


async def _exchange(
    client: httpx.AsyncClient, client_id: str, code: str, verifier: str
) -> httpx.Response:
    return await client.post(
        "/mcp-oauth/token",
        data={
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": _REDIRECT,
            "resource": _RESOURCE,
        },
    )


async def test_complete_consent_exchange_refresh_and_revoke(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    try:
        code, verifier = await _authorize(protocol_client, client_id)
        response = await _exchange(protocol_client, client_id, code, verifier)
        assert response.status_code == 200, response.text
        tokens = response.json()
        assert tokens["scope"] == "read:search"
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
        introspected = await protocol_client.get(
            "/mcp-oauth/introspect", headers=bearer
        )
        assert introspected.status_code == 200, introspected.text
        assert introspected.json()["resource"] == _RESOURCE
        assert "token" not in introspected.json()
        assert (
            await protocol_client.post("/search", headers=bearer)
        ).status_code == 200
        assert (
            await protocol_client.get("/unrelated", headers=bearer)
        ).status_code == 403
        refreshed = await protocol_client.post(
            "/mcp-oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": _RESOURCE,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
        revoked = await protocol_client.post(
            "/mcp-oauth/revoke",
            data={
                "client_id": client_id,
                "token": refreshed.json()["refresh_token"],
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert (
            await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
        ).status_code == 401
    finally:
        with get_catalog_session() as session:
            session.execute(
                delete(OAuthProviderClient).where(
                    OAuthProviderClient.client_id == client_id
                )
            )
            session.commit()


@pytest.mark.parametrize("protocol_session_strategy", [AuthBackend.JWT], indirect=True)
@pytest.mark.parametrize("legacy", [False, True])
async def test_jwt_login_refresh_between_consent_get_and_post(
    protocol_client: httpx.AsyncClient,
    protocol_session_strategy: TenantAwareRedisStrategy | SingleTenantJWTStrategy,
    legacy: bool,
) -> None:
    assert isinstance(protocol_session_strategy, SingleTenantJWTStrategy)
    if legacy:
        strategy = protocol_session_strategy
        token = generate_jwt(
            {
                "sub": protocol_client.headers["X-Mcp-Test-Owner"],
                "aud": strategy.token_audience,
                "iat": int(
                    (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()
                ),
            },
            strategy.encode_key,
            3600,
            algorithm=strategy.algorithm,
        )
        protocol_client.cookies.clear()
        protocol_client.cookies.set(FASTAPI_USERS_AUTH_COOKIE_NAME, token)
    client_id = await _register(protocol_client)
    handle, verifier = await _begin_authorization(protocol_client, client_id)
    details = await protocol_client.get(
        "/mcp-oauth/consent", params={"request": handle}
    )
    assert details.status_code == 200, details.text
    refreshed = await protocol_client.post("/auth/refresh")
    assert refreshed.status_code == 204, refreshed.text
    approved = await protocol_client.post(
        "/mcp-oauth/consent",
        headers={"Origin": _ORIGIN},
        json={
            "request_id": handle,
            "csrf_token": details.json()["csrf_token"],
            "decision": "allow",
        },
    )
    assert approved.status_code == 200, approved.text
    code = parse_qs(urlsplit(approved.json()["redirect_url"]).query)["code"][0]
    exchange = await _exchange(protocol_client, client_id, code, verifier)
    assert exchange.status_code == 200, exchange.text


@pytest.mark.parametrize("protocol_session_strategy", [AuthBackend.JWT], indirect=True)
async def test_separate_jwt_login_cannot_approve_pending_consent(
    protocol_client: httpx.AsyncClient,
    protocol_session_strategy: TenantAwareRedisStrategy | SingleTenantJWTStrategy,
    db_session: Session,
) -> None:
    assert isinstance(protocol_session_strategy, SingleTenantJWTStrategy)
    client_id = await _register(protocol_client)
    handle, _ = await _begin_authorization(protocol_client, client_id)
    details = await protocol_client.get(
        "/mcp-oauth/consent", params={"request": handle}
    )
    assert details.status_code == 200, details.text
    user = db_session.get(User, UUID(protocol_client.headers["X-Mcp-Test-Owner"]))
    assert user is not None
    second_login = await protocol_session_strategy.write_token(user)
    protocol_client.cookies.clear()
    protocol_client.cookies.set(FASTAPI_USERS_AUTH_COOKIE_NAME, second_login)
    approval = await protocol_client.post(
        "/mcp-oauth/consent",
        headers={"Origin": _ORIGIN},
        json={
            "request_id": handle,
            "csrf_token": details.json()["csrf_token"],
            "decision": "allow",
        },
    )
    assert approval.status_code == 400, approval.text


async def test_wrong_pkce_does_not_redeem_code(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    try:
        code, verifier = await _authorize(protocol_client, client_id)
        bad = await _exchange(protocol_client, client_id, code, "a" * 43)
        assert bad.status_code == 400, bad.text
        assert bad.headers["cache-control"] == "no-store"
        assert bad.headers["pragma"] == "no-cache"
        assert bad.headers["access-control-allow-origin"] == "*"
        assert bad.json()["error"] == "invalid_grant"
        assert (
            await _exchange(protocol_client, client_id, code, verifier)
        ).status_code == 200
        assert (
            await _exchange(protocol_client, client_id, code, verifier)
        ).status_code == 400
    finally:
        with get_catalog_session() as session:
            session.execute(
                delete(OAuthProviderClient).where(
                    OAuthProviderClient.client_id == client_id
                )
            )
            session.commit()


async def test_invalid_client_remains_401_without_revoking_grant(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    code, verifier = await _authorize(protocol_client, client_id)
    exchange = await _exchange(protocol_client, client_id, code, verifier)
    assert exchange.status_code == 200, exchange.text
    tokens = exchange.json()
    rejected = await protocol_client.post(
        "/mcp-oauth/token",
        data={
            "client_id": "unregistered-client",
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "resource": _RESOURCE,
        },
    )
    assert rejected.status_code == 401, rejected.text
    assert rejected.headers["cache-control"] == "no-store"
    assert rejected.headers["pragma"] == "no-cache"
    assert rejected.headers["access-control-allow-origin"] == "*"
    assert rejected.json()["error"] == "invalid_client"
    assert (
        await protocol_client.get(
            "/mcp-oauth/introspect",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    ).status_code == 200


async def test_metadata_and_duplicate_parameter_rejection(
    protocol_client: httpx.AsyncClient,
) -> None:
    response = await protocol_client.get("/mcp-oauth/metadata")
    assert response.json()["token_endpoint_auth_methods_supported"] == ["none"]
    response = await protocol_client.post(
        "/mcp-oauth/token",
        content="resource=x&resource=y",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert get_current_tenant_id() == "public"


async def test_resource_mismatch_preserves_code(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    code, verifier = await _authorize(protocol_client, client_id)
    response = await protocol_client.post(
        "/mcp-oauth/token",
        data={
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": _REDIRECT,
            "resource": _RESOURCE + "other",
        },
    )
    assert response.status_code == 400
    assert (
        await _exchange(protocol_client, client_id, code, verifier)
    ).status_code == 200


async def test_refresh_replay_revokes_new_tokens(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    code, verifier = await _authorize(protocol_client, client_id)
    tokens = (await _exchange(protocol_client, client_id, code, verifier)).json()
    request = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "resource": _RESOURCE,
    }
    refreshed = await protocol_client.post("/mcp-oauth/token", data=request)
    assert refreshed.status_code == 200, refreshed.text
    replayed = await protocol_client.post("/mcp-oauth/token", data=request)
    assert replayed.status_code == 400
    assert replayed.json()["error"] == "invalid_grant"
    for token in [tokens["access_token"], refreshed.json()["access_token"]]:
        assert (
            await protocol_client.get(
                "/mcp-oauth/introspect", headers={"Authorization": f"Bearer {token}"}
            )
        ).status_code == 401


async def test_cookie_cannot_override_invalid_oauth_bearer(
    protocol_client: httpx.AsyncClient,
) -> None:
    assert (await protocol_client.get("/mcp-oauth/introspect")).status_code == 401
    response = await protocol_client.post(
        "/search", headers={"Authorization": "Bearer onyx_mcp_a_invalid"}
    )
    assert response.status_code == 401


async def test_connected_apps_are_owner_only_and_disconnect_revokes_tokens(
    protocol_client: httpx.AsyncClient,
    db_session: Session,
    redis_client: Redis,
) -> None:
    client_id = await _register(protocol_client)
    code, verifier = await _authorize(protocol_client, client_id)
    exchange = await _exchange(protocol_client, client_id, code, verifier)
    assert exchange.status_code == 200, exchange.text
    tokens = exchange.json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    listed = await protocol_client.get("/mcp-oauth/grants")
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "no-store"
    grants = listed.json()
    assert len(grants) == 1
    assert grants[0]["client_id"] == client_id
    assert grants[0]["user_id"] == protocol_client.headers["X-Mcp-Test-Owner"]
    grant_path = f"/mcp-oauth/grants/{grants[0]['id']}"
    assert (
        await protocol_client.get("/mcp-oauth/grants", headers=bearer)
    ).status_code == 403
    assert (await protocol_client.delete(grant_path)).status_code == 403
    assert (
        await protocol_client.delete(
            grant_path, headers={"Origin": "https://other.example"}
        )
    ).status_code == 403

    other_user = create_test_user(
        db_session, "mcp_other_owner", assign_default_group=False
    )
    strategy = get_redis_strategy()
    other_session = await strategy.write_token(other_user)
    try:
        other_headers = {
            "Cookie": f"{FASTAPI_USERS_AUTH_COOKIE_NAME}={other_session}",
            "Origin": _ORIGIN,
        }
        other_list = await protocol_client.get(
            "/mcp-oauth/grants", headers=other_headers
        )
        assert other_list.status_code == 200, other_list.text
        assert other_list.json() == []
        assert (
            await protocol_client.delete(grant_path, headers=other_headers)
        ).status_code == 404
        assert (
            await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
        ).status_code == 200
    finally:
        await strategy.destroy_token(other_session, other_user)
        await redis_client.delete(f"{strategy.key_prefix}{other_session}")
        delete_test_user(db_session, other_user)
        db_session.commit()

    disconnected = await protocol_client.delete(grant_path, headers={"Origin": _ORIGIN})
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json() == {"revoked": True}
    assert (await protocol_client.get("/mcp-oauth/grants")).json() == []
    assert (
        await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
    ).status_code == 401
    refresh = await protocol_client.post(
        "/mcp-oauth/token",
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "resource": _RESOURCE,
        },
    )
    assert refresh.status_code == 400, refresh.text
    assert refresh.json()["error"] == "invalid_grant"


async def test_catalog_outage_does_not_consume_refresh_or_revoke_grant(
    protocol_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = await _register(protocol_client)
    code, verifier = await _authorize(protocol_client, client_id)
    exchange = await _exchange(protocol_client, client_id, code, verifier)
    assert exchange.status_code == 200, exchange.text
    tokens = exchange.json()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    refresh_request = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "resource": _RESOURCE,
    }
    unavailable = Mock(side_effect=SQLAlchemyError("catalog unavailable"))
    with monkeypatch.context() as outage:
        outage.setattr(oauth_provider, "mcp_oauth_owner_is_member", unavailable)
        outage.setattr(oauth_auth, "mcp_oauth_owner_is_member", unavailable)
        access = await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
        assert access.status_code == 503, access.text
        assert "www-authenticate" not in access.headers
        refresh = await protocol_client.post("/mcp-oauth/token", data=refresh_request)
        assert refresh.status_code == 503, refresh.text
        assert refresh.json()["error"] == "server_error"
        assert "www-authenticate" not in refresh.headers
    assert unavailable.call_count == 2
    assert (
        await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
    ).status_code == 200
    recovered = await protocol_client.post("/mcp-oauth/token", data=refresh_request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["refresh_token"] != tokens["refresh_token"]
    assert (
        await protocol_client.get("/mcp-oauth/introspect", headers=bearer)
    ).status_code == 200


async def test_consent_csrf_and_denial(protocol_client: httpx.AsyncClient) -> None:
    client_id = await _register(protocol_client)
    handle, _ = await _begin_authorization(protocol_client, client_id)
    details = await protocol_client.get(
        "/mcp-oauth/consent", params={"request": handle}
    )
    csrf = details.json()["csrf_token"]
    payload = {"request_id": handle, "csrf_token": csrf, "decision": "deny"}
    bad_origin = await protocol_client.post(
        "/mcp-oauth/consent",
        json=payload,
        headers={"Origin": "https://untrusted.example"},
    )
    assert bad_origin.status_code == 403
    bad_csrf = await protocol_client.post(
        "/mcp-oauth/consent",
        json={**payload, "csrf_token": "z" * 43},
        headers={"Origin": _ORIGIN},
    )
    assert bad_csrf.status_code == 400
    denied = await protocol_client.post(
        "/mcp-oauth/consent", json=payload, headers={"Origin": _ORIGIN}
    )
    assert denied.status_code == 200, denied.text
    parameters = parse_qs(urlsplit(denied.json()["redirect_url"]).query)
    assert parameters["error"] == ["access_denied"]
    assert "code" not in parameters
    repeated = await protocol_client.post(
        "/mcp-oauth/consent", json=payload, headers={"Origin": _ORIGIN}
    )
    assert repeated.status_code == 400


async def test_authorize_metadata_outage_does_not_retry_in_error_handler(
    protocol_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch = AsyncMock(side_effect=SSRFFetchError("metadata host unavailable"))
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    _cimd_fetcher.cache_clear()
    try:
        _, challenge = generate_pkce_pair()
        response = await protocol_client.get(
            "/mcp-oauth/authorize",
            params={
                "client_id": "https://client.example/oauth.json",
                "redirect_uri": _REDIRECT,
                "response_type": "code",
                "scope": "read:search",
                "resource": _RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 503, response.text
        assert response.json()["error"] == "server_error"
        fetch.assert_awaited_once()
    finally:
        _cimd_fetcher.cache_clear()


async def test_authorize_fetches_no_store_metadata_once_per_request(
    protocol_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = "https://client.example/no-store.json"
    fetch = AsyncMock(
        return_value=SSRFFetchResponse(
            content=json.dumps(
                {
                    "client_id": client_id,
                    "redirect_uris": [_REDIRECT],
                    "token_endpoint_auth_method": "none",
                }
            ).encode(),
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    )
    monkeypatch.setattr(cimd, "ssrf_safe_fetch_response", fetch)
    _cimd_fetcher.cache_clear()
    try:
        for expected_fetches in (1, 2):
            await _begin_authorization(protocol_client, client_id)
            assert fetch.await_count == expected_fetches
    finally:
        _cimd_fetcher.cache_clear()


async def test_unknown_tenant_revocation_is_success(
    protocol_client: httpx.AsyncClient,
) -> None:
    client_id = await _register(protocol_client)
    unknown = "onyx_mcp_r_unknown." + "a" * 43
    response = await protocol_client.post(
        "/mcp-oauth/revoke", data={"client_id": client_id, "token": unknown}
    )
    assert response.status_code == 200, response.text


async def test_public_client_cannot_register_confidential_method(
    protocol_client: httpx.AsyncClient,
) -> None:
    response = await protocol_client.post(
        "/mcp-oauth/register",
        json={
            "client_name": "Unsupported client",
            "redirect_uris": [_REDIRECT],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


@pytest.mark.parametrize("verifier", ["short", "a" * 129, "é" * 43, "a" * 42 + " "])
async def test_malformed_pkce_verifier_does_not_consume_code(
    protocol_client: httpx.AsyncClient, verifier: str
) -> None:
    client_id = await _register(protocol_client)
    code, valid_verifier = await _authorize(protocol_client, client_id)
    rejected = await _exchange(protocol_client, client_id, code, verifier)
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "invalid_request"
    assert (
        await _exchange(protocol_client, client_id, code, valid_verifier)
    ).status_code == 200
