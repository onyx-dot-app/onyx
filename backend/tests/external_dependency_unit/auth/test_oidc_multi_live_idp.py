"""Live-IdP coverage for the DB-backed multi-provider OIDC login against a real
OIDC server. Two providers run on one instance, so these guard the parts that
only break in a real authorization-code flow: discovery, code exchange, userinfo
and session issuance end to end, the per-provider gates that reject a login
(email domain, unverified address), and which pre-existing same-email rows a
login may claim when auto-linking is off.

Uses navikt/mock-oauth2-server, a real OIDC server whose per-login claims are
set through its documented username+claims form post, so there is no HTML
scraping. Requires it reachable at MOCK_OIDC_URL (default http://localhost:8086).
The suite skips when it is not.

The login flow runs in a single async test driven by httpx.AsyncClient, so every
request shares one event loop. A sync TestClient opens a fresh loop per request,
which strands the async DB connection the callback pooled on the prior request's
loop."""

import json
import os
from collections.abc import Generator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from onyx.auth.users import cookie_transport
from onyx.db.enums import AccountType, SSOProviderType
from onyx.db.models import ScimUserMapping, SSOProvider, User, User__UserGroup
from onyx.db.sso_provider import create_sso_provider
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server import oidc_multi

_MOCK_URL = os.environ.get("MOCK_OIDC_URL", "http://localhost:8086").rstrip("/")
_STATE_SECRET = "live-idp-test-secret"
_WEB_DOMAIN = "http://testserver"

_PROVIDER_A = "mock-a"
_PROVIDER_B = "mock-b"
_ISSUER_A = "issuer-a"
_ISSUER_B = "issuer-b"
_USER_A = "user-a@companya.com"
_USER_B = "user-b@companyb.com"
# A companyb.com identity offered to provider A, which only allows companya.com.
_EVE = "eve@companyb.com"

# Two providers that allow the same domain, to exercise the no-auto-link path.
_PROVIDER_C = "mock-c"
_PROVIDER_D = "mock-d"
_ISSUER_C = "issuer-c"
_ISSUER_D = "issuer-d"
_SHARED_USER = "shared@shared.com"
# Provisioned by SCIM before ever logging in, on the same shared.com domain.
_SCIM_USER = "provisioned@shared.com"

_SESSION_COOKIE = cookie_transport.cookie_name

_EMAILS = [_USER_A, _USER_B, _EVE, _SHARED_USER, _SCIM_USER]
_NAMES = [_PROVIDER_A, _PROVIDER_B, _PROVIDER_C, _PROVIDER_D]


def _mock_reachable() -> bool:
    try:
        httpx.get(
            f"{_MOCK_URL}/{_ISSUER_A}/.well-known/openid-configuration", timeout=2
        ).raise_for_status()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_mock_oidc() -> None:
    # Deferred to test time (not import/collection) so collecting the auth suite
    # never makes a network call.
    if not _mock_reachable():
        pytest.skip("requires navikt/mock-oauth2-server (MOCK_OIDC_URL)")


@pytest.fixture(autouse=True)
def _stub_idp_url_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # The mock IdP is http on loopback, which the authorize-path guard rejects
    # (https and public only). Stub it here. The guard is covered in
    # test_sso_url_guard.py.
    monkeypatch.setattr(oidc_multi, "validate_idp_url", lambda *_a, **_k: None)
    monkeypatch.setattr(
        oidc_multi, "validate_discovered_endpoints", lambda *_a, **_k: None
    )


def _config_url(issuer: str) -> str:
    return f"{_MOCK_URL}/{issuer}/.well-known/openid-configuration"


def _cleanup_db(db_session: Session) -> None:
    users = list(
        db_session.query(User).filter(
            User.email.in_(_EMAILS)  # ty: ignore[unresolved-attribute]
        )
    )
    user_ids = [user.id for user in users]
    if user_ids:
        # user__user_group is ON DELETE NO ACTION, so clear the group links first.
        # oauth_account is ON DELETE CASCADE, so the user delete removes it.
        db_session.query(User__UserGroup).filter(
            User__UserGroup.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        for user in users:
            db_session.delete(user)
    for provider in db_session.query(SSOProvider).filter(SSOProvider.name.in_(_NAMES)):
        db_session.delete(provider)
    db_session.commit()


def _create_provider(db_session: Session, name: str, issuer: str, domain: str) -> None:
    create_sso_provider(
        db_session=db_session,
        name=name,
        display_name=f"Mock OIDC {name}",
        provider_type=SSOProviderType.OIDC,
        config={
            "client_id": "onyx-live",
            "client_secret": "onyx-live-secret",
            "openid_config_url": _config_url(issuer),
        },
        allowed_email_domains=[domain],
    )


@pytest.fixture
def providers(db_session: Session) -> Generator[None, None, None]:
    _cleanup_db(db_session)
    _create_provider(db_session, _PROVIDER_A, _ISSUER_A, "companya.com")
    _create_provider(db_session, _PROVIDER_B, _ISSUER_B, "companyb.com")
    yield
    _cleanup_db(db_session)


@pytest.fixture
def same_domain_providers(db_session: Session) -> Generator[None, None, None]:
    _cleanup_db(db_session)
    _create_provider(db_session, _PROVIDER_C, _ISSUER_C, "shared.com")
    _create_provider(db_session, _PROVIDER_D, _ISSUER_D, "shared.com")
    yield
    _cleanup_db(db_session)


def _provision(
    db_session: Session, scim_managed: bool = False, **overrides: object
) -> User:
    """An account created ahead of its owner: complete, active, and holding only a
    throwaway password, with no oauth_account until someone logs in as it.

    ``scim_managed`` adds the mapping SCIM's POST /Users writes. The guard does not
    read it, so it is opt-in for the tests that reproduce the SCIM report.
    """
    pw_helper = PasswordHelper()
    user = User(
        **{
            "email": _SCIM_USER,
            "hashed_password": pw_helper.hash(pw_helper.generate()),
            "account_type": AccountType.STANDARD,
            "is_active": True,
            "is_verified": True,
            **overrides,
        }
    )
    db_session.add(user)
    db_session.flush()
    if scim_managed:
        db_session.add(ScimUserMapping(external_id="idp-ext-1", user_id=user.id))
    db_session.commit()
    return user


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(oidc_multi, "WEB_DOMAIN", _WEB_DOMAIN)
    monkeypatch.setattr(oidc_multi, "USER_AUTH_SECRET", _STATE_SECRET)
    fastapi_app = FastAPI()
    fastapi_app.include_router(oidc_multi.router)
    register_onyx_exception_handlers(fastapi_app)
    return fastapi_app


def _idp_login(authorization_url: str, email: str, email_verified: bool = True) -> str:
    """Post the identity to the IdP's login form and return the callback redirect
    location. The claims set what userinfo returns."""
    claims = json.dumps(
        {"sub": email, "email": email, "email_verified": email_verified}
    )
    with httpx.Client(follow_redirects=False, timeout=10) as browser:
        submit = browser.post(
            authorization_url, data={"username": email, "claims": claims}
        )
    assert submit.status_code == 302, submit.text
    return submit.headers["location"]


async def _drive_login(
    client: AsyncClient, provider: str, email: str, email_verified: bool = True
) -> httpx.Response:
    """Full authorization-code flow: authorize on the Onyx side (CSRF cookie lands
    in the client jar), log in at the IdP, then follow the redirect back into the
    Onyx callback."""
    resp = await client.get(f"/auth/oidc/{provider}/authorize")
    assert resp.status_code == 200, resp.text
    location = _idp_login(resp.json()["authorization_url"], email, email_verified)

    prefix = f"{_WEB_DOMAIN}/api"
    assert location.startswith(f"{prefix}/auth/oidc/{provider}/callback")
    # The web proxy strips /api before requests reach FastAPI.
    return await client.get(location.removeprefix(prefix))


def _user_by_email(db_session: Session, email: str) -> User:
    return (
        db_session.query(User)
        .filter(User.email == email)  # ty: ignore[invalid-argument-type]
        .one()
    )


@pytest.mark.usefixtures("providers")
def test_two_providers_resolve_to_distinct_issuers(app: FastAPI) -> None:
    client = TestClient(app)
    urls = {
        name: client.get(f"/auth/oidc/{name}/authorize").json()["authorization_url"]
        for name in (_PROVIDER_A, _PROVIDER_B)
    }
    assert f"/{_ISSUER_A}/" in urls[_PROVIDER_A]
    assert f"/{_ISSUER_B}/" in urls[_PROVIDER_B]


@pytest.mark.asyncio
@pytest.mark.usefixtures("providers")
async def test_two_providers_live_login_and_domain_gate(
    app: FastAPI, db_session: Session
) -> None:
    logins = ((_PROVIDER_A, _USER_A), (_PROVIDER_B, _USER_B))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        # Both providers log in end-to-end on the one instance.
        for provider, email in logins:
            resp = await _drive_login(client, provider, email)
            assert resp.status_code == 302, resp.text
            assert _SESSION_COOKIE in resp.cookies

        # Provider A only allows companya.com, so a companyb.com identity is rejected.
        blocked = await _drive_login(client, _PROVIDER_A, _EVE)
        assert blocked.status_code == 400, blocked.text
        assert _SESSION_COOKIE not in blocked.cookies

    db_session.expire_all()
    for provider, email in logins:
        assert [
            oa.oauth_name for oa in _user_by_email(db_session, email).oauth_accounts
        ] == [provider]
    eve_rows = db_session.query(User).filter(
        User.email == _EVE  # ty: ignore[invalid-argument-type]
    )
    assert eve_rows.count() == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("providers")
async def test_unverified_email_is_rejected(app: FastAPI, db_session: Session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        resp = await _drive_login(client, _PROVIDER_A, _USER_A, email_verified=False)
        assert resp.status_code == 400, resp.text
        assert _SESSION_COOKIE not in resp.cookies

    db_session.expire_all()
    rows = db_session.query(User).filter(
        User.email == _USER_A  # ty: ignore[invalid-argument-type]
    )
    assert rows.count() == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("same_domain_providers")
async def test_second_provider_does_not_link_existing_account(
    app: FastAPI, db_session: Session
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        first = await _drive_login(client, _PROVIDER_C, _SHARED_USER)
        assert first.status_code == 302, first.text
        assert _SESSION_COOKIE in first.cookies

        # Auto-linking is off, so the same email through a second provider is
        # rejected rather than attached to the existing account.
        second = await _drive_login(client, _PROVIDER_D, _SHARED_USER)
        assert second.status_code == 400, second.text
        assert _SESSION_COOKIE not in second.cookies

    db_session.expire_all()
    user = _user_by_email(db_session, _SHARED_USER)
    assert [oa.oauth_name for oa in user.oauth_accounts] == [_PROVIDER_C]


@pytest.mark.asyncio
@pytest.mark.usefixtures("same_domain_providers")
async def test_provisioned_user_links_on_first_login(
    app: FastAPI, db_session: Session
) -> None:
    """Provisioning creates the account ahead of the person, so their first login
    finds a same-email row with no oauth_account and must claim that row rather
    than reject it. Auto-linking stays off throughout."""
    provisioned_id = _provision(db_session, scim_managed=True).id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        resp = await _drive_login(client, _PROVIDER_C, _SCIM_USER)
        assert resp.status_code == 302, resp.text
        assert _SESSION_COOKIE in resp.cookies

    db_session.expire_all()
    user = _user_by_email(db_session, _SCIM_USER)
    # Claiming the row rather than creating a second one is the whole point: the
    # SCIM mapping is keyed on user_id, so a new row would strand it.
    assert user.id == provisioned_id
    assert [oa.oauth_name for oa in user.oauth_accounts] == [_PROVIDER_C]
    assert db_session.query(ScimUserMapping).filter_by(user_id=user.id).count() == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("same_domain_providers")
async def test_claimed_row_rejects_second_provider(
    app: FastAPI, db_session: Session
) -> None:
    """A provisioned row is claimable only until an IdP claims it. A second
    provider asserting the same address is then refused, and the first provider's
    link is left untouched."""
    _provision(db_session, scim_managed=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        first = await _drive_login(client, _PROVIDER_C, _SCIM_USER)
        assert first.status_code == 302, first.text

        second = await _drive_login(client, _PROVIDER_D, _SCIM_USER)
        assert second.status_code == 400, second.text
        assert _SESSION_COOKIE not in second.cookies

    db_session.expire_all()
    user = _user_by_email(db_session, _SCIM_USER)
    assert [oa.oauth_name for oa in user.oauth_accounts] == [_PROVIDER_C]


@pytest.mark.asyncio
@pytest.mark.usefixtures("same_domain_providers")
async def test_renamed_row_is_not_claimable(app: FastAPI, db_session: Session) -> None:
    """A row moved onto this address by a rename must not be claimable. Whoever
    performed the rename would otherwise hand the original account, and its
    history and privileges, to any identity that can assert the new address."""
    renamed = _provision(db_session, prior_emails=["someone-else@shared.com"])
    renamed_id = renamed.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        resp = await _drive_login(client, _PROVIDER_C, _SCIM_USER)
        assert resp.status_code == 400, resp.text
        assert _SESSION_COOKIE not in resp.cookies

    db_session.expire_all()
    user = _user_by_email(db_session, _SCIM_USER)
    assert user.id == renamed_id
    assert user.oauth_accounts == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("same_domain_providers")
async def test_deactivated_row_is_not_linked(app: FastAPI, db_session: Session) -> None:
    """Claiming commits, so a deprovisioned row must come back unlinked. Linking
    it would hand the account to this identity the moment SCIM reactivates it."""
    _provision(db_session, is_active=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEB_DOMAIN) as client:
        resp = await _drive_login(client, _PROVIDER_C, _SCIM_USER)
        assert resp.status_code == 400, resp.text
        assert _SESSION_COOKIE not in resp.cookies

    db_session.expire_all()
    assert _user_by_email(db_session, _SCIM_USER).oauth_accounts == []
