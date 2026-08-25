"""Unit coverage for the DB-backed SAML router: the OneLogin settings built from
a provider row (fixed ACS), fail-closed resolution by name and by issuer, the
issuer extraction that routes the single callback, the per-provider email-domain
gate, email extraction from SAML attributes, and the post-login redirect. No DB
or live IdP."""

import base64
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.responses import RedirectResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from sqlalchemy.orm import Session
from starlette.responses import Response as StarletteResponse

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import SAMLProviderConfig
from onyx.error_handling.exceptions import OnyxError
from onyx.server import saml_multi
from onyx.server.saml import _sanitize_relay_state
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


def test_build_saml_settings_requested_authn_context_defaults_true() -> None:
    settings = saml_multi.build_saml_settings(_config())
    assert settings["security"]["requestedAuthnContext"] is True


def test_build_saml_settings_requested_authn_context_can_be_disabled() -> None:
    settings = saml_multi.build_saml_settings(_config(request_authn_context=False))
    assert settings["security"]["requestedAuthnContext"] is False


def _provider(**overrides: object) -> SSOProvider:
    base: dict[str, Any] = dict(
        provider_type=SSOProviderType.SAML,
        allowed_email_domains=[],
        config=make_mock_sensitive_value(dict(_IDP)),
    )
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


def test_extract_issuer_response_level() -> None:
    xml = _RESPONSE.format(body="<saml:Issuer>https://idp.example.com/e</saml:Issuer>")
    assert (
        saml_multi._extract_issuer_from_saml_response(_encode(xml))
        == "https://idp.example.com/e"
    )


def test_extract_issuer_assertion_fallback() -> None:
    xml = _RESPONSE.format(
        body="<saml:Assertion><saml:Issuer>https://idp.example.com/e"
        "</saml:Issuer></saml:Assertion>"
    )
    assert (
        saml_multi._extract_issuer_from_saml_response(_encode(xml))
        == "https://idp.example.com/e"
    )


def test_extract_issuer_malformed_raises() -> None:
    with pytest.raises(OnyxError):
        saml_multi._extract_issuer_from_saml_response(_encode("not xml <"))


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


# ---------------------------------------------------------------------------
# Post-login redirect: the IdP posts SAMLResponse via a real top-level
# navigation, so the callback must wrap auth_backend.login()'s bare 204 in a
# redirect the same way onyx.auth.users.complete_login_flow does for OIDC/OAuth,
# or the browser is left stuck on the IdP's blank auto-submit page.
# ---------------------------------------------------------------------------


class _FakeCallbackAuth:
    def __init__(self, _req: dict[str, Any], old_settings: Any) -> None:
        del old_settings

    def process_response(self) -> None:
        pass

    def get_errors(self) -> list[str]:
        return []

    def get_last_error_reason(self) -> str:
        return ""

    def is_authenticated(self) -> bool:
        return True

    def get_attribute(self, key: str) -> list[str] | None:
        return {"email": ["user@example.com"]}.get(key)

    def get_attributes(self) -> dict[str, list[str]]:
        return {"email": ["user@example.com"]}


def _stub_callback_dependencies(
    monkeypatch: pytest.MonkeyPatch, *, relay_state: str | None
) -> StarletteResponse:
    xml = _RESPONSE.format(body=f"<saml:Issuer>{_IDP['idp_entity_id']}</saml:Issuer>")
    post_data: dict[str, Any] = {"SAMLResponse": _encode(xml)}
    if relay_state is not None:
        post_data["RelayState"] = relay_state

    async def _fake_prepare(_request: Any) -> dict[str, Any]:
        return {"post_data": post_data, "get_data": {}}

    monkeypatch.setattr(saml_multi, "prepare_from_fastapi_request", _fake_prepare)
    monkeypatch.setattr(
        saml_multi, "fetch_sso_providers", lambda **_kw: [_provider(name="saml")]
    )
    monkeypatch.setattr(saml_multi, "OneLogin_Saml2_Auth", _FakeCallbackAuth)

    async def _fake_upsert(email: str) -> Any:
        del email
        return SimpleNamespace(is_active=True)

    monkeypatch.setattr(saml_multi, "upsert_saml_user", _fake_upsert)

    async def _fake_capture(*_args: Any, **_kwargs: Any) -> None:
        pass

    monkeypatch.setattr(saml_multi, "capture_saml_login_claims", _fake_capture)

    login_response = StarletteResponse(status_code=204)
    login_response.headers["set-cookie"] = "onyxauth=abc; Path=/; HttpOnly"

    async def _fake_login(_strategy: Any, _user: Any) -> StarletteResponse:
        return login_response

    monkeypatch.setattr(saml_multi.auth_backend, "login", _fake_login)
    return login_response


@pytest.mark.asyncio
async def test_process_saml_callback_redirects_and_carries_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_callback_dependencies(monkeypatch, relay_state="/settings")

    async def _fake_on_after_login(*_args: Any, **_kwargs: Any) -> None:
        pass

    user_manager = cast(Any, SimpleNamespace(on_after_login=_fake_on_after_login))
    response = await saml_multi._process_saml_callback(
        cast(Any, SimpleNamespace()), _DB, cast(Any, None), user_manager
    )

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert response.headers["location"] == "/settings"
    assert response.headers["set-cookie"] == "onyxauth=abc; Path=/; HttpOnly"


@pytest.mark.asyncio
async def test_process_saml_callback_falls_back_to_app_without_relay_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_callback_dependencies(monkeypatch, relay_state=None)

    async def _fake_on_after_login(*_args: Any, **_kwargs: Any) -> None:
        pass

    user_manager = cast(Any, SimpleNamespace(on_after_login=_fake_on_after_login))
    response = await saml_multi._process_saml_callback(
        cast(Any, SimpleNamespace()), _DB, cast(Any, None), user_manager
    )

    assert response.headers["location"] == "/app"


@pytest.mark.asyncio
async def test_process_saml_callback_rejects_external_relay_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_callback_dependencies(
        monkeypatch, relay_state="https://evil.example.com/steal"
    )

    async def _fake_on_after_login(*_args: Any, **_kwargs: Any) -> None:
        pass

    user_manager = cast(Any, SimpleNamespace(on_after_login=_fake_on_after_login))
    response = await saml_multi._process_saml_callback(
        cast(Any, SimpleNamespace()), _DB, cast(Any, None), user_manager
    )

    assert response.headers["location"] == "/app"


@pytest.mark.asyncio
async def test_process_saml_callback_rejects_protocol_relative_relay_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "///evil.example" has no netloc under urlparse, but some browsers still
    # resolve it as scheme-relative navigation to evil.example.
    _stub_callback_dependencies(monkeypatch, relay_state="///evil.example")

    async def _fake_on_after_login(*_args: Any, **_kwargs: Any) -> None:
        pass

    user_manager = cast(Any, SimpleNamespace(on_after_login=_fake_on_after_login))
    response = await saml_multi._process_saml_callback(
        cast(Any, SimpleNamespace()), _DB, cast(Any, None), user_manager
    )

    assert response.headers["location"] == "/app"


# ---------------------------------------------------------------------------
# _sanitize_relay_state: internal-path guard shared by the /authorize `next`
# param and the callback's RelayState handling.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "relative/no-leading-slash",
        "//evil.example",
        "///evil.example",
        "////evil.example",
        "/\\evil.example",
        "/path:with-colon",
        "https://evil.example/steal",
        "javascript:alert(1)",
    ],
)
def test_sanitize_relay_state_rejects_unsafe_values(candidate: str | None) -> None:
    assert _sanitize_relay_state(candidate) is None


@pytest.mark.parametrize(
    "candidate",
    ["/app", "/settings?x=1", "/path#fragment"],
)
def test_sanitize_relay_state_accepts_internal_paths(candidate: str) -> None:
    assert _sanitize_relay_state(candidate) == candidate
