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

import dns.exception
import dns.resolver
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, delete, inspect, select
from sqlalchemy.orm import Session

from ee.onyx.auth.sso_domain_verification import (
    revalidate_tenant_domains,
    verification_record,
    verify_domain_via_dns,
)
from ee.onyx.db.tenant_sso_domain import (
    claim_email_domains,
    is_claimed_domain,
    is_email_domain_verified,
    lookup_tenant_id_for_email_domain,
    mark_domain_unverified,
    mark_domain_verified,
)
from ee.onyx.db.user_tenant_mapping import (
    is_active_member,
    lookup_tenant_id_for_login,
)
from onyx.auth.sso_tenant_token import (
    decode_sso_tenant_token,
    generate_sso_tenant_token,
)
from onyx.db.models import (
    TenantSSODomain,
    UserTenantMapping,
    UserTenantMappingOAuthAccount,
)
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


@pytest.fixture()
def catalog_with_domains(catalog_session: Session) -> Generator[Session, None, None]:
    """`claim_email_domains` and verification write `tenant_sso_domain`, which a
    single-tenant dev database never creates."""
    bind = catalog_session.get_bind()
    table = cast(Table, TenantSSODomain.__table__)
    created_here = not inspect(bind).has_table(table.name, schema="public")
    if created_here:
        table.create(bind=bind)
        catalog_session.commit()
    try:
        yield catalog_session
    finally:
        if created_here:
            catalog_session.rollback()
            table.drop(bind=bind)
            catalog_session.commit()


def _clear_domains(session: Session, tenant_id: str) -> None:
    session.execute(
        delete(TenantSSODomain).where(TenantSSODomain.tenant_id == tenant_id)
    )
    session.commit()


class _TxtRecord:
    """One TXT answer whose joined strings decode to `value`."""

    def __init__(self, value: str) -> None:
        self.strings = [value.encode()]


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_claim_records_a_pending_unverified_domain(
    catalog_with_domains: Session,
) -> None:
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.example"
    try:
        claim_email_domains(tenant_id, [domain])
        catalog_with_domains.expire_all()
        row = catalog_with_domains.get(TenantSSODomain, (tenant_id, domain))
        assert row is not None
        assert row.verified_at is None
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_unverified_domain_does_not_route(catalog_with_domains: Session) -> None:
    """A claim proves nothing until verified, so it must not route anyone."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.example"
    try:
        claim_email_domains(tenant_id, [domain])
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") is None
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_dns_verification_marks_verified_and_routes(
    catalog_with_domains: Session,
) -> None:
    """Publishing the TXT record the workspace names verifies the domain, after
    which it routes its users."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [domain])
        _host, value = verification_record(tenant_id, domain)
        with patch("dns.resolver.Resolver") as resolver_cls:
            resolver_cls.return_value.resolve.return_value = [_TxtRecord(value)]
            assert verify_domain_via_dns(tenant_id, domain) is True
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") == tenant_id
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_dns_verification_without_the_record_does_not_route(
    catalog_with_domains: Session,
) -> None:
    """A missing or wrong TXT record leaves the domain unverified and unrouted."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [domain])
        with patch("dns.resolver.Resolver") as resolver_cls:
            resolver_cls.return_value.resolve.return_value = [
                _TxtRecord("onyx-verify=wrong")
            ]
            assert verify_domain_via_dns(tenant_id, domain) is False
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") is None
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_revalidation_drops_a_domain_whose_record_disappeared(
    catalog_with_domains: Session,
) -> None:
    """A verified domain whose TXT record is later removed stops routing, so a
    workspace that has lost control of a domain cannot keep pulling its users."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [domain])
        mark_domain_verified(tenant_id, domain)
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") == tenant_id
        with patch("dns.resolver.Resolver") as resolver_cls:
            resolver_cls.return_value.resolve.side_effect = dns.resolver.NXDOMAIN
            revalidate_tenant_domains(tenant_id)
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") is None
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_revalidation_keeps_a_domain_whose_record_is_present(
    catalog_with_domains: Session,
) -> None:
    """A verified domain whose TXT record still resolves keeps routing."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [domain])
        mark_domain_verified(tenant_id, domain)
        _host, value = verification_record(tenant_id, domain)
        with patch("dns.resolver.Resolver") as resolver_cls:
            resolver_cls.return_value.resolve.return_value = [_TxtRecord(value)]
            revalidate_tenant_domains(tenant_id)
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") == tenant_id
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_revalidation_keeps_a_domain_on_a_transient_dns_failure(
    catalog_with_domains: Session,
) -> None:
    """A resolver timeout is inconclusive, so it must not drop a good domain."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [domain])
        mark_domain_verified(tenant_id, domain)
        with patch("dns.resolver.Resolver") as resolver_cls:
            resolver_cls.return_value.resolve.side_effect = dns.exception.Timeout
            revalidate_tenant_domains(tenant_id)
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") == tenant_id
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_catalog_writes_match_a_claim_regardless_of_domain_casing(
    catalog_with_domains: Session,
) -> None:
    """Catalog keys are normalized, so a caller passing mixed case or surrounding
    whitespace resolves the claim it owns rather than missing it and leaving the
    domain verified and routable."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.com"
    try:
        claim_email_domains(tenant_id, [f"  {domain.upper()}  "])
        assert is_claimed_domain(tenant_id, f"  {domain.upper()}  ")

        mark_domain_verified(tenant_id, domain.upper())
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") == tenant_id

        mark_domain_unverified(tenant_id, f" {domain.upper()} ")
        assert lookup_tenant_id_for_email_domain(f"user@{domain}") is None
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


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


@patch("ee.onyx.db.tenant_sso_domain.MULTI_TENANT", True)
def test_is_email_domain_verified_only_after_verification(
    catalog_with_domains: Session,
) -> None:
    """A tenant-controlled IdP may vouch for an address only once the workspace
    has verified its domain, so a pending claim and another workspace's
    verification must both read as unverified."""
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    other_tenant = f"tenant_{uuid4().hex[:12]}"
    domain = f"acme-{uuid4().hex[:8]}.example"
    try:
        claim_email_domains(tenant_id, [domain])
        assert is_email_domain_verified(tenant_id, f"user@{domain}") is False

        mark_domain_verified(tenant_id, domain)
        assert is_email_domain_verified(tenant_id, f"user@{domain}") is True

        # Verification belongs to the workspace that proved control, not to any
        # workspace that merely lists the domain.
        assert is_email_domain_verified(other_tenant, f"user@{domain}") is False
        # An unknown domain and a malformed address are both unverified.
        assert is_email_domain_verified(tenant_id, "user@unclaimed.example") is False
        assert is_email_domain_verified(tenant_id, "no-at-sign") is False
    finally:
        _clear_domains(catalog_with_domains, tenant_id)


@pytest.fixture()
def catalog_with_oauth(catalog_session: Session) -> Generator[Session, None, None]:
    """The OAuth-subject link table lives in the multi-tenant catalog, which a
    single-tenant dev database never creates."""
    bind = catalog_session.get_bind()
    table = cast(Table, UserTenantMappingOAuthAccount.__table__)
    created_here = not inspect(bind).has_table(table.name, schema="public")
    if created_here:
        table.create(bind=bind)
        catalog_session.commit()
    try:
        yield catalog_session
    finally:
        if created_here:
            catalog_session.rollback()
            table.drop(bind=bind)
            catalog_session.commit()


@patch("ee.onyx.db.user_tenant_mapping.MULTI_TENANT", True)
def test_is_active_member_only_for_a_current_active_membership(
    catalog_with_oauth: Session,
) -> None:
    """The verified-domain gate exempts current members. A retired (inactive)
    membership must not count, or a former member could be reactivated on an
    unverified domain."""
    email = _new_email()
    tenant_id = f"tenant_{uuid4().hex[:12]}"
    oauth_name, account_id = "oidc", uuid4().hex
    try:
        assert is_active_member(tenant_id, email, oauth_name, account_id) is False

        _add_mapping(catalog_with_oauth, email, tenant_id, active=False)
        assert is_active_member(tenant_id, email, oauth_name, account_id) is False

        catalog_with_oauth.execute(
            delete(UserTenantMapping).where(UserTenantMapping.email == email)
        )
        _add_mapping(catalog_with_oauth, email, tenant_id, active=True)
        assert is_active_member(tenant_id, email, oauth_name, account_id) is True

        # A subject linked to the active membership also identifies the member,
        # even after the provider renames their address.
        catalog_with_oauth.add(
            UserTenantMappingOAuthAccount(
                oauth_name=oauth_name,
                account_id=account_id,
                email=email,
                tenant_id=tenant_id,
            )
        )
        catalog_with_oauth.commit()
        assert (
            is_active_member(tenant_id, "renamed@example.com", oauth_name, account_id)
            is True
        )
    finally:
        _cleanup(catalog_with_oauth, email)
