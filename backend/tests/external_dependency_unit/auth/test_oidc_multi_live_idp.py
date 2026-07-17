"""Live-IdP coverage for the DB-backed multi-provider OIDC login against a real
OIDC server: two providers on one instance complete the authorization-code flow
(discovery fetch, code exchange, userinfo, JIT user provisioning, session
issuance), the per-provider email-domain gate rejects a cross-domain login, an
unverified email is rejected, and with auto-linking off a second provider does
not attach to an existing account.

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
from httpx import ASGITransport
from httpx import AsyncClient
from sqlalchemy.orm import Session

from onyx.auth.users import cookie_transport
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.models import User
from onyx.db.models import User__UserGroup
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

_SESSION_COOKIE = cookie_transport.cookie_name

_EMAILS = [_USER_A, _USER_B, _EVE, _SHARED_USER]
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
