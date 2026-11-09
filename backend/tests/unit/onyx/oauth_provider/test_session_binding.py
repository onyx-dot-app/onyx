from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import pytest
from fastapi_users.jwt import generate_jwt
from starlette.requests import Request

from onyx.auth.schemas import AuthBackend
from onyx.auth.users import SingleTenantJWTStrategy
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.oauth_provider import api
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


@pytest.fixture
def jwt_strategy(monkeypatch: pytest.MonkeyPatch) -> SingleTenantJWTStrategy:
    strategy = SingleTenantJWTStrategy(
        secret="mcp-consent-test-secret-longer-than-32-bytes", lifetime_seconds=3600
    )
    monkeypatch.setattr(app_configs, "AUTH_BACKEND", AuthBackend.JWT)
    monkeypatch.setattr(api, "get_jwt_strategy", lambda: strategy)
    return strategy


def session_request(
    token: str,
    *,
    source: Literal["cookie", "bearer"] = "cookie",
    incidental: str | None = None,
    credential: UsageCredentialType = UsageCredentialType.SESSION,
) -> Request:
    cookie = token if source == "cookie" else incidental
    authorization = incidental if source == "cookie" else f"Bearer {token}"
    headers = []
    if cookie is not None:
        headers.append(
            (b"cookie", f"{FASTAPI_USERS_AUTH_COOKIE_NAME}={cookie}".encode())
        )
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "headers": headers,
            "state": {
                "usage_credential": UsageCredentialIdentity(credential),
                "authenticated_session_token": token,
            },
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["cookie", "bearer"])
async def test_legacy_jwt_refresh_preserves_consent_binding(
    jwt_strategy: SingleTenantJWTStrategy, source: Literal["cookie", "bearer"]
) -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    legacy = generate_jwt(
        {
            "sub": str(user.id),
            "aud": jwt_strategy.token_audience,
            "iat": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()),
        },
        jwt_strategy.encode_key,
        3600,
        algorithm=jwt_strategy.algorithm,
    )
    refreshed = await jwt_strategy.refresh_token(legacy, user)
    assert refreshed != legacy
    assert api._session_hash(
        session_request(legacy, source=source), user
    ) == api._session_hash(session_request(refreshed, source=source), user)


@pytest.mark.asyncio
async def test_new_logins_do_not_share_consent_binding(
    jwt_strategy: SingleTenantJWTStrategy,
) -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    first = await jwt_strategy.write_token(user)
    other = await jwt_strategy.write_token(user)
    refreshed = await jwt_strategy.refresh_token(first, user)
    assert api._session_hash(session_request(first), user) == api._session_hash(
        session_request(refreshed), user
    )
    assert api._session_hash(session_request(first), user) != api._session_hash(
        session_request(other), user
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["cookie", "bearer"])
async def test_incidental_credential_change_still_changes_binding(
    jwt_strategy: SingleTenantJWTStrategy, source: Literal["cookie", "bearer"]
) -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    token = await jwt_strategy.write_token(user)
    assert api._session_hash(
        session_request(token, source=source, incidental="first"), user
    ) != api._session_hash(
        session_request(token, source=source, incidental="second"), user
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "invalid_jwt",
        "service_account",
        "other_users_token",
        "no_credentials",
        "multi_tenant_jwt",
    ],
)
async def test_unbound_or_foreign_sessions_fail_closed(
    jwt_strategy: SingleTenantJWTStrategy,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    request = session_request(await jwt_strategy.write_token(user))
    if case == "invalid_jwt":
        request = session_request("invalid-jwt")
    elif case == "service_account":
        user.account_type = AccountType.SERVICE_ACCOUNT
    elif case == "other_users_token":
        other = User(id=uuid4(), account_type=AccountType.STANDARD)
        request = session_request(await jwt_strategy.write_token(other))
    elif case == "no_credentials":
        request = Request(
            {
                "type": "http",
                "headers": [],
                "state": {
                    "usage_credential": UsageCredentialIdentity(
                        UsageCredentialType.SESSION
                    )
                },
            }
        )
    elif case == "multi_tenant_jwt":
        monkeypatch.setattr(api, "MULTI_TENANT", True)
        request = session_request(
            "external-idp-token", source="bearer", credential=UsageCredentialType.JWT
        )
    with pytest.raises(OnyxError):
        api._session_hash(request, user)


def test_external_idp_jwt_binds_to_the_bearer_not_session_state(
    jwt_strategy: SingleTenantJWTStrategy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = jwt_strategy
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    user = User(id=uuid4(), account_type=AccountType.STANDARD)

    def binding(bearer: str, session_token: str) -> str:
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", f"Bearer {bearer}".encode())],
                "state": {
                    "usage_credential": UsageCredentialIdentity(
                        UsageCredentialType.JWT
                    ),
                    "authenticated_session_token": session_token,
                },
            }
        )
        return api._session_hash(request, user)

    assert binding("idp-a", "first") == binding("idp-a", "second")
    assert binding("idp-a", "first") != binding("idp-b", "first")


@pytest.mark.asyncio
async def test_incidental_text_cannot_impersonate_a_normalized_session(
    jwt_strategy: SingleTenantJWTStrategy,
) -> None:
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    first = await jwt_strategy.write_token(user)
    second = await jwt_strategy.write_token(user)
    first_id = jwt_strategy.get_session_id(first, user)
    second_id = jwt_strategy.get_session_id(second, user)
    cookie_login = session_request(first, incidental=f"jwt-session:{second_id}")
    bearer_login = session_request(
        second, source="bearer", incidental=f"jwt-session:{first_id}"
    )
    assert api._session_hash(cookie_login, user) != api._session_hash(
        bearer_login, user
    )
