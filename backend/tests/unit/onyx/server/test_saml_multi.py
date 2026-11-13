"""Unit coverage for the DB-backed SAML router: the OneLogin settings built from
a provider row (fixed ACS), the callback request data OneLogin checks against that
ACS, fail-closed resolution by name and by issuer, the issuer and InResponseTo
extraction that routes the single callback, the one-time binding of a response
to the AuthnRequest Onyx issued, the ticketed handoff to /complete that ties the
session to the browser that started sign-in, assertion replay rejection, the per-provider
email-domain gate, and email extraction from SAML attributes. No DB or live IdP."""

import base64
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi_users.authentication import Strategy
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from onyx.auth.users import UserManager
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider, User
from onyx.db.sso_provider import SAMLProviderConfig
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server import saml, saml_multi
from onyx.utils.sensitive import make_mock_sensitive_value

_IDP = {
    "idp_entity_id": "https://idp.example.com/entity",
    "idp_sso_url": "https://idp.example.com/sso",
    "idp_x509_cert": "IDPCERT",
    "sp_entity_id": "https://onyx.example.com/saml",
}
# Test doubles: the router functions never touch the real Session, only pass it
# to the monkeypatched fetch.
_DB = cast(Session, object())


def _config(**overrides: Any) -> SAMLProviderConfig:
    return SAMLProviderConfig(**{**_IDP, **overrides})


def test_build_saml_settings_fixed_acs() -> None:
    settings = saml_multi.build_saml_settings(
        _config(sp_x509_cert="SPCERT", sp_private_key="SPKEY")
    )
    assert settings["strict"] is True
    assert settings["sp"]["assertionConsumerService"]["url"].endswith(
        "/auth/saml/callback"
    )
    assert settings["sp"]["entityId"] == _IDP["sp_entity_id"]
    assert settings["sp"]["x509cert"] == "SPCERT"
    assert settings["sp"]["privateKey"] == "SPKEY"
    assert settings["idp"]["entityId"] == _IDP["idp_entity_id"]
    assert settings["idp"]["singleSignOnService"]["url"] == _IDP["idp_sso_url"]
    assert settings["idp"]["x509cert"] == "IDPCERT"


def test_build_saml_settings_optional_sp_defaults_empty() -> None:
    settings = saml_multi.build_saml_settings(_config())
    assert settings["sp"]["x509cert"] == ""
    assert settings["sp"]["privateKey"] == ""


def _callback_request(cookie: str | None = None) -> Request:
    # TLS ends at the reverse proxy, so the API server sees plain HTTP.
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/auth/saml/callback",
            "query_string": b"",
            "headers": [(b"cookie", cookie.encode())] if cookie else [],
            "client": ("10.0.0.5", 51234),
            "server": ("api_server", 8080),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "web_domain",
    [
        "https://onyx.example.com:3000",
        "https://onyx.example.com",
        "http://localhost:3000",
    ],
)
async def test_callback_request_url_matches_acs(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    monkeypatch.setattr(saml, "WEB_DOMAIN", web_domain)
    monkeypatch.setattr(saml_multi, "WEB_DOMAIN", web_domain)

    request_data = await saml.prepare_from_fastapi_request(_callback_request())
    settings = saml_multi.build_saml_settings(_config())

    assert (
        OneLogin_Saml2_Utils.get_self_url_no_query(request_data)
        == settings["sp"]["assertionConsumerService"]["url"]
    )


def _provider(**overrides: object) -> SSOProvider:
    base: dict[str, Any] = {
        "name": "okta",
        "provider_type": SSOProviderType.SAML,
        "allowed_email_domains": [],
        "config": make_mock_sensitive_value(dict(_IDP)),
    }
    base.update(overrides)
    return cast(SSOProvider, SimpleNamespace(**base))


def test_domain_gate_empty_allows_any() -> None:
    saml_multi._enforce_allowed_email_domain(_provider(), "x@anything.com")


def test_domain_gate_allows_listed_domain() -> None:
    provider = _provider(allowed_email_domains=["companya.com"])
    saml_multi._enforce_allowed_email_domain(provider, "user@CompanyA.com")


def test_domain_gate_strips_whitespace() -> None:
    provider = _provider(allowed_email_domains=["companya.com"])
    saml_multi._enforce_allowed_email_domain(provider, "user@companya.com ")


def test_domain_gate_denies_other_domain() -> None:
    provider = _provider(allowed_email_domains=["companya.com"])
    with pytest.raises(OnyxError):
        saml_multi._enforce_allowed_email_domain(provider, "user@companyb.com")


def test_resolve_by_name_fail_closed_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saml_multi, "fetch_sso_provider_by_name", lambda **_kw: None)
    with pytest.raises(OnyxError):
        saml_multi._resolve_saml_provider(_DB, "missing")


def test_resolve_by_name_fail_closed_non_saml(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(provider_type=SSOProviderType.OIDC)
    monkeypatch.setattr(
        saml_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    with pytest.raises(OnyxError):
        saml_multi._resolve_saml_provider(_DB, "oidc-row")


def test_resolve_by_name_returns_config(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    monkeypatch.setattr(
        saml_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    resolved, config = saml_multi._resolve_saml_provider(_DB, "saml")
    assert resolved is provider
    assert config == _config()


def test_resolve_by_issuer_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    monkeypatch.setattr(saml_multi, "fetch_sso_providers", lambda **_kw: [provider])
    resolved, config = saml_multi._resolve_saml_provider_by_issuer(
        _DB, _IDP["idp_entity_id"]
    )
    assert resolved is provider
    assert config == _config()


def test_resolve_by_issuer_no_match_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saml_multi, "fetch_sso_providers", lambda **_kw: [_provider()])
    with pytest.raises(OnyxError):
        saml_multi._resolve_saml_provider_by_issuer(_DB, "https://other.example.com")


_RESPONSE = (
    '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
    'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{body}</samlp:Response>'
)


def _encode(xml: str) -> str:
    return base64.b64encode(xml.encode()).decode()


def test_read_header_response_level_issuer() -> None:
    xml = _RESPONSE.format(body="<saml:Issuer>https://idp.example.com/e</saml:Issuer>")
    header = saml_multi._read_saml_response_header(_encode(xml))
    assert header.issuer == "https://idp.example.com/e"
    assert header.in_response_to is None


def test_read_header_assertion_issuer_fallback() -> None:
    xml = _RESPONSE.format(
        body="<saml:Assertion><saml:Issuer>https://idp.example.com/e"
        "</saml:Issuer></saml:Assertion>"
    )
    assert (
        saml_multi._read_saml_response_header(_encode(xml)).issuer
        == "https://idp.example.com/e"
    )


def test_read_header_in_response_to() -> None:
    xml = _RESPONSE.replace("<samlp:Response ", '<samlp:Response InResponseTo="REQ1" ')
    xml = xml.format(body="<saml:Issuer>https://idp.example.com/e</saml:Issuer>")
    assert saml_multi._read_saml_response_header(_encode(xml)).in_response_to == "REQ1"


def test_read_header_malformed_raises() -> None:
    with pytest.raises(OnyxError):
        saml_multi._read_saml_response_header(_encode("not xml <"))


class _FakeCache:
    """The CacheBackend subset the SAML router uses, without expiry."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def set(
        self, key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> None:
        del ex
        self.values[key] = value if isinstance(value, bytes) else str(value).encode()

    def getdel(self, key: str) -> bytes | None:
        return self.values.pop(key, None)

    def set_if_absent(
        self, key: str, value: str | bytes | int | float, ex: int | None
    ) -> bool:
        if key in self.values:
            return False
        self.set(key, value, ex)
        return True


class _FakeLoginAuth:
    def login(self, return_to: str | None = None) -> str:
        del return_to
        return "https://idp.example.com/sso?SAMLRequest=x"

    def get_last_request_id(self) -> str:
        return "REQ1"


@pytest.mark.asyncio
async def test_authorize_stores_request_id_for_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(saml_multi, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        saml_multi,
        "_resolve_saml_provider",
        lambda _db, _name: (_provider(), _config()),
    )

    async def _fake_build(_request: Request, _settings: object) -> OneLogin_Saml2_Auth:
        return cast(OneLogin_Saml2_Auth, _FakeLoginAuth())

    monkeypatch.setattr(saml_multi, "_build_saml_auth", _fake_build)

    response = await saml_multi.saml_login_for_provider(
        "okta", _callback_request(), _DB
    )

    (stored,) = cache.values.values()
    pending = saml_multi._PendingSamlRequest.model_validate_json(stored)
    assert pending.idp_entity_id == _IDP["idp_entity_id"]
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(saml_multi._login_cookie_name("REQ1") + "=")
    assert "HttpOnly" in set_cookie
    browser_secret = set_cookie.split("=", 1)[1].split(";", 1)[0]
    assert pending.browser_secret_hash == saml_multi._sha256(browser_secret)


class _FakeCallbackAuth:
    """Stands in for OneLogin: records the request id it was asked to enforce
    and reports a valid assertion."""

    processed_request_ids: list[str | None] = []
    assertion_id = "ASSERTION1"

    def __init__(self, _req: dict[str, Any], old_settings: dict[str, Any]) -> None:
        pass

    def process_response(self, request_id: str | None = None) -> None:
        self.processed_request_ids.append(request_id)

    def get_errors(self) -> list[str]:
        return []

    def get_last_error_reason(self) -> str:
        return ""

    def is_authenticated(self) -> bool:
        return True

    def get_last_assertion_id(self) -> str:
        return self.assertion_id

    def get_last_assertion_not_on_or_after(self) -> int | None:
        return None

    def get_attribute(self, key: str) -> list[str] | None:
        return ["a@b.com"] if key == "email" else None

    def get_attributes(self) -> dict[str, list[str]]:
        return {"email": ["a@b.com"]}


class _FakeUserManager:
    async def on_after_login(
        self, user: User, request: Request, response: Response
    ) -> None:
        del user, request, response


_BROWSER_SECRET = "browser-secret"


def _stub_callback(
    monkeypatch: pytest.MonkeyPatch,
    cache: _FakeCache,
    in_response_to: str | None,
    relay_state: str | None = None,
) -> None:
    xml = _RESPONSE
    if in_response_to is not None:
        xml = xml.replace(
            "<samlp:Response ", f'<samlp:Response InResponseTo="{in_response_to}" '
        )
    xml = xml.format(body=f"<saml:Issuer>{_IDP['idp_entity_id']}</saml:Issuer>")
    post_data: dict[str, str] = {"SAMLResponse": _encode(xml)}
    if relay_state is not None:
        post_data["RelayState"] = relay_state

    async def _fake_prepare(_request: Request) -> dict[str, Any]:
        return {"post_data": post_data, "get_data": {}}

    async def _fake_upsert(email: str) -> User:
        return cast(User, SimpleNamespace(email=email, is_active=True))

    async def _fake_capture(*_args: object) -> None:
        return None

    async def _fake_login(_strategy: object, _user: User) -> Response:
        response = Response(status_code=204)
        response.set_cookie("fastapiusersauth", "session-token")
        return response

    _FakeCallbackAuth.processed_request_ids = []
    monkeypatch.setattr(saml_multi, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(saml_multi, "prepare_from_fastapi_request", _fake_prepare)
    monkeypatch.setattr(
        saml_multi,
        "_resolve_saml_provider_by_issuer",
        lambda _db, _issuer: (_provider(), _config()),
    )
    monkeypatch.setattr(saml_multi, "OneLogin_Saml2_Auth", _FakeCallbackAuth)
    monkeypatch.setattr(
        saml_multi,
        "_resolve_saml_provider",
        lambda _db, _name: (_provider(), _config()),
    )
    monkeypatch.setattr(saml_multi, "upsert_saml_user", _fake_upsert)
    monkeypatch.setattr(saml_multi, "capture_saml_login_claims", _fake_capture)
    monkeypatch.setattr(saml_multi.auth_backend, "login", _fake_login)


async def _run_callback() -> Response:
    return await saml_multi._process_saml_callback(_callback_request(), _DB)


def _ticket_from(response: Response) -> str:
    location = response.headers["location"]
    assert location.startswith(saml_multi.WEB_DOMAIN + "/auth/saml/complete?ticket=")
    return location.rsplit("ticket=", 1)[1]


async def _run_complete(
    ticket: str,
    request_id: str = "REQ1",
    browser_secret: str | None = _BROWSER_SECRET,
) -> Response:
    cookie = (
        f"{saml_multi._login_cookie_name(request_id)}={browser_secret}"
        if browser_secret is not None
        else None
    )
    return await saml_multi._complete_saml_login(
        _callback_request(cookie),
        ticket,
        _DB,
        cast(Strategy[User, Any], object()),
        cast(UserManager, _FakeUserManager()),
    )


def _pending_request(cache: _FakeCache, request_id: str, issuer: str) -> None:
    cache.set(
        saml_multi._cache_key(saml_multi._AUTHN_REQUEST_KEY_PREFIX, request_id),
        saml_multi._PendingSamlRequest(
            idp_entity_id=issuer,
            browser_secret_hash=saml_multi._sha256(_BROWSER_SECRET),
        ).model_dump_json(),
    )


@pytest.mark.asyncio
async def test_callback_without_in_response_to_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    _stub_callback(monkeypatch, cache, in_response_to=None)
    _pending_request(cache, "REQ1", _IDP["idp_entity_id"])

    with pytest.raises(OnyxError):
        await _run_callback()
    assert _FakeCallbackAuth.processed_request_ids == []


@pytest.mark.asyncio
async def test_callback_unknown_request_id_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_callback(monkeypatch, _FakeCache(), in_response_to="REQ1")

    with pytest.raises(OnyxError):
        await _run_callback()
    assert _FakeCallbackAuth.processed_request_ids == []


@pytest.mark.asyncio
async def test_callback_request_id_for_other_provider_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    _stub_callback(monkeypatch, cache, in_response_to="REQ1")
    _pending_request(cache, "REQ1", "https://other-idp.example.com/entity")

    with pytest.raises(OnyxError):
        await _run_callback()
    assert _FakeCallbackAuth.processed_request_ids == []


@pytest.mark.asyncio
async def test_callback_consumes_request_id_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    _stub_callback(monkeypatch, cache, in_response_to="REQ1")
    _pending_request(cache, "REQ1", _IDP["idp_entity_id"])

    response = await _run_callback()

    assert response.status_code == 303
    assert _FakeCallbackAuth.processed_request_ids == ["REQ1"]
    ticket = _ticket_from(response)
    stored = cache.values[
        saml_multi._cache_key(saml_multi._LOGIN_TICKET_KEY_PREFIX, ticket)
    ]
    login = saml_multi._SamlLoginTicket.model_validate_json(stored)
    assert login.email == "a@b.com"
    assert login.request_id == "REQ1"
    with pytest.raises(OnyxError):
        await _run_callback()


@pytest.mark.asyncio
async def test_callback_rejects_replayed_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    _stub_callback(monkeypatch, cache, in_response_to="REQ1")
    _pending_request(cache, "REQ1", _IDP["idp_entity_id"])
    await _run_callback()

    # A second pending request answered with the same assertion id.
    _stub_callback(monkeypatch, cache, in_response_to="REQ2")
    _pending_request(cache, "REQ2", _IDP["idp_entity_id"])
    with pytest.raises(OnyxError):
        await _run_callback()


async def _ticket_for_login(
    monkeypatch: pytest.MonkeyPatch, cache: _FakeCache, relay_state: str | None
) -> str:
    _stub_callback(monkeypatch, cache, in_response_to="REQ1", relay_state=relay_state)
    _pending_request(cache, "REQ1", _IDP["idp_entity_id"])
    return _ticket_from(await _run_callback())


@pytest.mark.asyncio
async def test_complete_without_login_cookie_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    ticket = await _ticket_for_login(monkeypatch, cache, relay_state=None)

    with pytest.raises(OnyxError):
        await _run_complete(ticket, browser_secret=None)


@pytest.mark.asyncio
async def test_complete_with_other_browsers_cookie_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    ticket = await _ticket_for_login(monkeypatch, cache, relay_state=None)

    with pytest.raises(OnyxError):
        await _run_complete(ticket, browser_secret="someone-elses-secret")


@pytest.mark.asyncio
async def test_complete_unknown_ticket_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_callback(monkeypatch, _FakeCache(), in_response_to="REQ1")

    with pytest.raises(OnyxError):
        await _run_complete("no-such-ticket")


@pytest.mark.asyncio
async def test_complete_rejects_when_provider_was_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    ticket = await _ticket_for_login(monkeypatch, cache, relay_state=None)

    def _disabled(_db: Session, _name: str) -> tuple[SSOProvider, SAMLProviderConfig]:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "unknown SAML provider")

    monkeypatch.setattr(saml_multi, "_resolve_saml_provider", _disabled)
    with pytest.raises(OnyxError):
        await _run_complete(ticket)


@pytest.mark.asyncio
async def test_complete_logs_in_once_and_clears_login_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    ticket = await _ticket_for_login(monkeypatch, cache, relay_state="/settings")

    response = await _run_complete(ticket)

    assert response.status_code == 302
    assert response.headers["location"] == saml_multi.WEB_DOMAIN + "/settings"
    cookies = response.headers.getlist("set-cookie")
    assert any(
        cookie.startswith("fastapiusersauth=session-token") for cookie in cookies
    )
    assert any(
        cookie.startswith(saml_multi._login_cookie_name("REQ1") + '=""')
        for cookie in cookies
    )
    with pytest.raises(OnyxError):
        await _run_complete(ticket)


@pytest.mark.asyncio
async def test_complete_without_relay_state_lands_on_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _FakeCache()
    ticket = await _ticket_for_login(monkeypatch, cache, relay_state=None)

    response = await _run_complete(ticket)

    assert response.headers["location"] == saml_multi.WEB_DOMAIN + "/"


class _FakeAuth:
    def __init__(self, attrs: dict[str, list[str]]) -> None:
        self._attrs = attrs

    def get_attribute(self, key: str) -> list[str] | None:
        return self._attrs.get(key)

    def get_attributes(self) -> dict[str, list[str]]:
        return self._attrs

    def get_errors(self) -> list[str]:
        return []

    def get_last_error_reason(self) -> str:
        return ""


def _fake_auth(attrs: dict[str, list[str]]) -> OneLogin_Saml2_Auth:
    return cast(OneLogin_Saml2_Auth, _FakeAuth(attrs))


def test_extract_email_configured_attribute() -> None:
    auth = _fake_auth({"urn:custom:mail": ["a@b.com"]})
    assert (
        saml_multi._extract_user_email(auth, _config(email_attribute="urn:custom:mail"))
        == "a@b.com"
    )


def test_extract_email_common_key() -> None:
    auth = _fake_auth({"email": ["a@b.com"]})
    assert saml_multi._extract_user_email(auth, _config()) == "a@b.com"


def test_extract_email_case_insensitive_fallback() -> None:
    auth = _fake_auth({"EMAIL": ["a@b.com"]})
    assert saml_multi._extract_user_email(auth, _config()) == "a@b.com"


def test_extract_email_missing_raises() -> None:
    auth = _fake_auth({"displayName": ["Alice"]})
    with pytest.raises(OnyxError):
        saml_multi._extract_user_email(auth, _config())
