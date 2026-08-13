"""Guard the cloud SSO discovery contract.

Discovery runs before the visitor has authenticated, so it must answer only
about workspaces the address already belongs to, must not accept an invitation
on their behalf, and must not distinguish "no such workspace" from "workspace
without SSO" in what it returns.
"""

from collections.abc import Generator
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, delete, inspect, select
from sqlalchemy.orm import Session

from ee.onyx.db.user_tenant_mapping import lookup_tenant_id_for_login
from onyx.auth.sso_tenant_token import (
    decode_sso_tenant_token,
    generate_sso_tenant_token,
)
from onyx.db.models import UserTenantMapping
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.server.sso_discovery import router as sso_discovery_router

_TEST_SECRET = "test-user-auth-secret-at-least-32-bytes-long"


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(sso_discovery_router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def catalog_session(db_session: Session) -> Generator[Session, None, None]:
    """`user_tenant_mapping` lives in the multi-tenant catalog migrations, which
    a single-tenant dev database never runs. Create it for the test and leave a
    real catalog untouched."""
    bind = db_session.get_bind()
    table = cast(Table, UserTenantMapping.__table__)
    created_here = not inspect(bind).has_table(table.name, schema="public")
    if created_here:
        table.create(bind=bind)
        db_session.commit()
    try:
        yield db_session
    finally:
        if created_here:
            db_session.rollback()
            table.drop(bind=bind)
            db_session.commit()


def _new_email() -> str:
    return f"discovery-{uuid4().hex[:10]}@example.com"


def _add_mapping(session: Session, email: str, tenant_id: str, active: bool) -> None:
    session.add(UserTenantMapping(email=email, tenant_id=tenant_id, active=active))
    session.commit()


def _cleanup(session: Session, email: str) -> None:
    session.execute(delete(UserTenantMapping).where(UserTenantMapping.email == email))
    session.commit()


def _mapping_active(session: Session, email: str) -> bool:
    session.expire_all()
    return bool(
        session.scalar(
            select(UserTenantMapping.active).where(UserTenantMapping.email == email)
        )
    )


@patch("ee.onyx.db.user_tenant_mapping.MULTI_TENANT", True)
def test_lookup_does_not_accept_a_pending_invitation(
    catalog_session: Session,
) -> None:
    """An unauthenticated lookup that flipped `active` would enroll someone in a
    workspace by typing their address into a login form."""
    email = _new_email()
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    _add_mapping(catalog_session, email, tenant_id, active=False)
    try:
        assert lookup_tenant_id_for_login(email) == tenant_id
        assert _mapping_active(catalog_session, email) is False
    finally:
        _cleanup(catalog_session, email)


@patch("ee.onyx.db.user_tenant_mapping.MULTI_TENANT", True)
def test_lookup_refuses_to_choose_between_invitations(
    catalog_session: Session,
) -> None:
    email = _new_email()
    _add_mapping(catalog_session, email, f"tenant_{uuid4().hex[:12]}", active=False)
    _add_mapping(catalog_session, email, f"tenant_{uuid4().hex[:12]}", active=False)
    try:
        assert lookup_tenant_id_for_login(email) is None
    finally:
        _cleanup(catalog_session, email)


@pytest.mark.usefixtures("catalog_session")
@patch("ee.onyx.db.user_tenant_mapping.MULTI_TENANT", True)
def test_lookup_returns_none_for_unknown_address() -> None:
    assert lookup_tenant_id_for_login(_new_email()) is None


@patch("onyx.server.sso_discovery.MULTI_TENANT", True)
@patch("onyx.server.sso_discovery._enforce_discovery_rate_limit", new=AsyncMock())
def test_unknown_address_returns_an_empty_list(client: TestClient) -> None:
    """Same shape an SSO-less workspace returns, so the response cannot be used
    to tell whether an address belongs to a customer."""
    response = client.post("/auth/sso/discover", json={"email": _new_email()})
    assert response.status_code == 200
    assert response.json() == {"providers": []}


def test_malformed_address_is_rejected(client: TestClient) -> None:
    response = client.post("/auth/sso/discover", json={"email": "not-an-email"})
    assert response.status_code == 422


@patch("onyx.server.sso_discovery.MULTI_TENANT", True)
@patch(
    "onyx.server.sso_discovery.get_async_redis_connection",
    side_effect=ConnectionError("redis is down"),
)
def test_lookup_refuses_when_the_limiter_is_unavailable(
    _redis: object, client: TestClient
) -> None:
    """The limiter is the only bound on probing this endpoint, so losing it has
    to cost the lookup rather than the bound."""
    response = client.post("/auth/sso/discover", json={"email": _new_email()})
    assert response.status_code == OnyxErrorCode.RATE_LIMITED.status_code


def test_workspace_pin_round_trips_and_rejects_another_signer() -> None:
    """The pin decides which workspace's IdP configuration a login reads, so a
    token this deployment did not sign must not select one."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"

    with patch("onyx.auth.sso_tenant_token.USER_AUTH_SECRET", _TEST_SECRET):
        token = generate_sso_tenant_token(tenant_id)
        assert decode_sso_tenant_token(token) == tenant_id

    # Same token, a different signing secret. Flipping a character instead would
    # be flaky: base64url characters can differ while the decoded bytes match.
    with patch("onyx.auth.sso_tenant_token.USER_AUTH_SECRET", _TEST_SECRET + "x"):
        with pytest.raises(OnyxError):
            decode_sso_tenant_token(token)


@patch("onyx.auth.sso_tenant_token.USER_AUTH_SECRET", _TEST_SECRET)
@patch("onyx.server.sso_discovery.MULTI_TENANT", True)
@patch("onyx.server.sso_discovery._enforce_discovery_rate_limit", new=AsyncMock())
def test_resolved_workspace_authorize_urls_carry_a_workspace_pin(
    client: TestClient,
) -> None:
    """Authorize has no session to read the workspace from, so discovery has to
    hand it over in the URL it returns."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    fake_provider: Any = type(
        "FakeProvider",
        (),
        {
            "name": "okta",
            "display_name": "Okta",
            "provider_type": "OIDC",
        },
    )()

    with (
        patch(
            "onyx.server.sso_discovery.fetch_ee_implementation_or_noop",
            return_value=lambda _email: tenant_id,
        ),
        patch("onyx.server.sso_discovery.get_session_with_tenant"),
        patch(
            "onyx.server.sso_discovery.fetch_sso_providers",
            return_value=[fake_provider],
        ),
    ):
        response = client.post("/auth/sso/discover", json={"email": _new_email()})

    assert response.status_code == 200
    [provider] = response.json()["providers"]
    assert provider["authorize_url"].startswith("/api/auth/oidc/okta/authorize?")
    assert "workspace_token=" in provider["authorize_url"]
