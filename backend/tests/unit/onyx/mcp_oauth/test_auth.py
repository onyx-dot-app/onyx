from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastmcp import FastMCP
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.requests import Request

from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.mcp_oauth.auth import extract_mcp_oauth_bearer
from onyx.mcp_oauth.models import MCPOAuthIntrospection
from onyx.mcp_server import api as mcp_api
from onyx.mcp_server import auth as mcp_auth
from onyx.server.mcp_oauth import protocol as oauth_protocol
from onyx.server.mcp_oauth.api import _session_hash
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


@pytest.fixture
def introspection_backend(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", True)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", "https://onyx.example")
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    monkeypatch.setattr(mcp_auth.time, "time", lambda: 1000)
    backend = AsyncMock()
    monkeypatch.setattr(mcp_auth, "get_http_client", lambda: backend)
    return backend


@pytest.fixture
def introspection() -> MCPOAuthIntrospection:
    return MCPOAuthIntrospection(
        client_id="registered-client",
        scopes=["read:search"],
        resource="https://onyx.example/mcp/",
        expires_at=1900,
        subject=str(uuid4()),
        grant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_oauth_verifier_preserves_validated_identity(
    introspection_backend: AsyncMock, introspection: MCPOAuthIntrospection
) -> None:
    introspection_backend.get.return_value = httpx.Response(
        200, json=introspection.model_dump(mode="json")
    )
    token = "onyx_mcp_a_test"
    verified = await mcp_auth.OnyxTokenVerifier().verify_token(token)
    assert verified is not None
    assert verified.token == token
    assert verified.client_id == introspection.client_id
    assert verified.subject == introspection.subject
    assert verified.resource == introspection.resource
    assert verified.scopes == introspection.scopes
    assert verified.expires_at == introspection.expires_at
    introspection_backend.get.assert_awaited_once()
    request = introspection_backend.get.call_args
    assert request.args[0].endswith("/mcp-oauth/introspect")
    assert request.kwargs["headers"] == {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["resource", "scopes", "expires_at", "client_id"])
async def test_oauth_verifier_rejects_incorrect_claims(
    introspection_backend: AsyncMock,
    introspection: MCPOAuthIntrospection,
    field: str,
) -> None:
    if field == "resource":
        introspection.resource = "https://other.example/mcp/"
    elif field == "scopes":
        introspection.scopes = ["read:search", "write:admin"]
    elif field == "expires_at":
        introspection.expires_at = 1000
    else:
        introspection.client_id = ""
    introspection_backend.get.return_value = httpx.Response(
        200, json=introspection.model_dump(mode="json")
    )
    assert await mcp_auth.OnyxTokenVerifier().verify_token("onyx_mcp_a_test") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 402, 403, 503])
async def test_oauth_verifier_distinguishes_rejection_from_outage(
    introspection_backend: AsyncMock, status_code: int
) -> None:
    introspection_backend.get.return_value = httpx.Response(status_code)
    verifier = mcp_auth.OnyxTokenVerifier()
    if status_code == 401:
        assert await verifier.verify_token("onyx_mcp_a_test") is None
        return
    with pytest.raises(OnyxError) as caught:
        await verifier.verify_token("onyx_mcp_a_test")
    assert (
        caught.value.error_code
        == {
            402: OnyxErrorCode.SUBSCRIPTION_INACTIVE,
            403: OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            503: OnyxErrorCode.SERVICE_UNAVAILABLE,
        }[status_code]
    )


@pytest.fixture(autouse=True)
def isolate_app_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_api,
        "create_prometheus_instrumentator",
        lambda: Instrumentator(
            # The library's in-progress gauge ignores the supplied registry.
            should_instrument_requests_inprogress=False,
            registry=CollectorRegistry(),
        ),
    )


@pytest.mark.parametrize(
    "headers",
    [
        [
            (b"authorization", b"Bearer onyx_mcp_a_invalid"),
            (b"authorization", b"Bearer onyx_mcp_a_invalid"),
        ],
        [
            (b"authorization", b"Bearer onyx_mcp_a_invalid"),
            (b"x-onyx-authorization", b"Bearer other-token"),
        ],
        [(b"authorization", b"Basic onyx_mcp_a_invalid")],
        [(b"authorization", b"Bearer onyx_mcp_a_invalid extra")],
    ],
)
def test_conflicting_or_malformed_mcp_headers_fail_closed(
    headers: list[tuple[bytes, bytes]],
) -> None:
    request = Request({"type": "http", "headers": headers})
    with pytest.raises(OnyxError) as caught:
        extract_mcp_oauth_bearer(request)
    assert caught.value.error_code == OnyxErrorCode.UNAUTHENTICATED


def test_non_mcp_credentials_keep_existing_auth_path() -> None:
    request = Request(
        {"type": "http", "headers": [(b"authorization", b"Bearer onyx_pat_example")]}
    )
    assert extract_mcp_oauth_bearer(request) is None


def test_consent_binding_tracks_bearer_even_with_an_unrelated_cookie() -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    fingerprints = []
    for token in ("first-session", "second-session"):
        request = Request(
            {
                "type": "http",
                "headers": [
                    (b"cookie", f"{FASTAPI_USERS_AUTH_COOKIE_NAME}=unrelated".encode()),
                    (b"authorization", f"Bearer {token}".encode()),
                ],
                "state": {
                    "usage_credential": UsageCredentialIdentity(
                        UsageCredentialType.SESSION
                    )
                },
            }
        )
        fingerprints.append(_session_hash(request, user))
    assert fingerprints[0] != fingerprints[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [
        (402, OnyxErrorCode.SUBSCRIPTION_INACTIVE),
        (503, OnyxErrorCode.SERVICE_UNAVAILABLE),
    ],
)
async def test_introspection_preserves_billing_and_outage_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_code: OnyxErrorCode,
) -> None:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", True)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", "http://localhost:3000")
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    backend = AsyncMock()
    backend.get.return_value = httpx.Response(status_code)
    monkeypatch.setattr(mcp_auth, "get_http_client", lambda: backend)
    server = FastMCP("outage-test", auth=mcp_auth.build_mcp_server_auth())
    monkeypatch.setattr(mcp_api, "mcp_server", server)
    app = mcp_api.create_mcp_fastapi_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/", headers={"Authorization": "Bearer onyx_mcp_a_invalid"}
        )
    assert response.status_code == status_code, response.text
    assert response.json()["error_code"] == error_code.code
    assert "www-authenticate" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("forwarded", "addresses"),
    [
        (
            ("1.1.1.1, 8.8.8.8, 10.0.0.8", "1.1.1.1, 9.9.9.9, 10.0.0.8"),
            ("8.8.8.8", "9.9.9.9"),
        ),
        (("10.1.2.3", "10.1.2.4"), ("10.1.2.3", "10.1.2.4")),
    ],
)
async def test_oauth_rate_limit_uses_forwarded_client_address(
    monkeypatch: pytest.MonkeyPatch,
    forwarded: tuple[str, str],
    addresses: tuple[str, str],
) -> None:
    limiter = AsyncMock(return_value=True)
    monkeypatch.setattr(oauth_protocol, "allow_mcp_oauth_request", limiter)
    for chain in forwarded:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp-oauth/register",
                "client": ("10.0.0.9", 1234),
                "headers": [
                    (
                        b"x-forwarded-for",
                        chain.encode("ascii"),
                    )
                ],
            }
        )
        assert await oauth_protocol._rate_limit(request, "register") is None
    buckets = [call.args[0] for call in limiter.await_args_list]
    assert buckets == [
        f"register:ip:{addresses[0]}",
        "register:global",
        f"register:ip:{addresses[1]}",
        "register:global",
    ]


@pytest.mark.asyncio
async def test_insufficient_scope_has_discovery_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", True)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", "http://localhost:3000")
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    monkeypatch.setattr(mcp_api, "MCP_SERVER_CORS_ORIGINS", ["https://client.example"])
    backend = AsyncMock()
    backend.get.return_value = httpx.Response(403)
    monkeypatch.setattr(mcp_auth, "get_http_client", lambda: backend)
    server = FastMCP("scope-test", auth=mcp_auth.build_mcp_server_auth())
    monkeypatch.setattr(mcp_api, "mcp_server", server)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(mcp_api.create_mcp_fastapi_app()),
        base_url="http://localhost:3000",
    ) as client:
        response = await client.post(
            "/",
            headers={
                "Authorization": "Bearer onyx_mcp_a_test",
                "Origin": "https://client.example",
            },
        )
    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == "https://client.example"
    exposed = {
        header.strip().lower()
        for header in response.headers.get("access-control-expose-headers", "").split(
            ","
        )
    }
    assert {"www-authenticate", "mcp-session-id"} <= exposed
    challenge = response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert 'scope="read:search"' in challenge
    assert (
        'resource_metadata="http://localhost:3000/.well-known/oauth-protected-resource/mcp/"'
        in challenge
    )


@pytest.mark.asyncio
async def test_discovery_aliases_and_challenge_point_to_same_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", True)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", "http://localhost:3000")
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    server = FastMCP("discovery-test", auth=mcp_auth.build_mcp_server_auth())
    monkeypatch.setattr(mcp_api, "mcp_server", server)
    app = mcp_api.create_mcp_fastapi_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost:3000"
    ) as client:
        challenge = await client.post("/")
        assert challenge.status_code == 401
        metadata_url = (
            challenge.headers["www-authenticate"]
            .split('resource_metadata="')[1]
            .split('"')[0]
        )
        discovered = await client.get(metadata_url)
        alias = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert discovered.status_code == alias.status_code == 200
    assert discovered.json() == alias.json()
    assert discovered.json()["resource"] == "http://localhost:3000/mcp/"
    assert discovered.json()["authorization_servers"] == [
        "http://localhost:3000/api/mcp-oauth"
    ]


@pytest.mark.asyncio
async def test_disabled_feature_advertises_no_oauth_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_ENABLED", False)
    server = FastMCP("disabled-test", auth=mcp_auth.build_mcp_server_auth())
    monkeypatch.setattr(mcp_api, "mcp_server", server)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(mcp_api.create_mcp_fastapi_app()),
        base_url="http://localhost",
    ) as client:
        response = await client.post("/")
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 401
    assert "resource_metadata" not in response.headers["www-authenticate"]
    assert metadata.status_code == 404
