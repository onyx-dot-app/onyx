"""Unit coverage for the DB-backed OIDC/Google router: fail-closed provider
resolution, the per-provider client cache (keying, config-rotation bust),
per-provider client construction, and OAuth state/CSRF validation. No DB, no
network, no live IdP."""

from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.auth.users import CSRF_TOKEN_COOKIE_NAME
from onyx.auth.users import CSRF_TOKEN_KEY
from onyx.auth.users import decode_and_validate_oauth_state
from onyx.auth.users import generate_csrf_token
from onyx.auth.users import generate_state_token
from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server import oidc_multi
from onyx.utils.sensitive import make_mock_sensitive_value

_OIDC_CONFIG = {
    "client_id": "cid",
    "client_secret": "secret",
    "openid_config_url": "https://idp.example.com/.well-known/openid-configuration",
}
_GOOGLE_CONFIG = {"client_id": "gid", "client_secret": "gsecret"}
_DB = cast(Session, object())
_TEST_SECRET = "unit-test-secret"


def _provider(**overrides: object) -> SSOProvider:
    base: dict[str, Any] = dict(
        name="okta",
        provider_type=SSOProviderType.OIDC,
        allowed_email_domains=["companya.com"],
        config=make_mock_sensitive_value(dict(_OIDC_CONFIG)),
    )
    base.update(overrides)
    return cast(SSOProvider, SimpleNamespace(**base))


def test_resolve_oidc_returns_config(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    monkeypatch.setattr(
        oidc_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    resolved, config = oidc_multi._resolve_oidc_provider(_DB, "okta")
    assert resolved is provider
    assert config == {**_OIDC_CONFIG, "legacy_callback": False}


def test_resolve_google_returns_config(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(
        name="google",
        provider_type=SSOProviderType.GOOGLE_OAUTH,
        config=make_mock_sensitive_value(dict(_GOOGLE_CONFIG)),
    )
    monkeypatch.setattr(
        oidc_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    _resolved, config = oidc_multi._resolve_oidc_provider(_DB, "google")
    assert config == {**_GOOGLE_CONFIG, "legacy_callback": False}


def test_resolve_fail_closed_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oidc_multi, "fetch_sso_provider_by_name", lambda **_kw: None)
    with pytest.raises(OnyxError):
        oidc_multi._resolve_oidc_provider(_DB, "missing")


def test_resolve_fail_closed_saml_type(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(provider_type=SSOProviderType.SAML)
    monkeypatch.setattr(
        oidc_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    with pytest.raises(OnyxError):
        oidc_multi._resolve_oidc_provider(_DB, "saml-row")


def test_resolve_fail_closed_incomplete_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # An OIDC row missing openid_config_url fails model validation -> fail closed.
    provider = _provider(
        config=make_mock_sensitive_value({"client_id": "c", "client_secret": "s"})
    )
    monkeypatch.setattr(
        oidc_multi, "fetch_sso_provider_by_name", lambda **_kw: provider
    )
    with pytest.raises(OnyxError):
        oidc_multi._resolve_oidc_provider(_DB, "okta")


def test_cache_key_stable_and_config_sensitive() -> None:
    provider = _provider()
    key = oidc_multi._get_cache_key(provider, dict(_OIDC_CONFIG))
    assert key == oidc_multi._get_cache_key(provider, dict(_OIDC_CONFIG))
    rotated = oidc_multi._get_cache_key(
        provider, {**_OIDC_CONFIG, "client_secret": "rotated"}
    )
    assert key != rotated


def test_build_client_google_uses_provider_name() -> None:
    provider = _provider(name="google", provider_type=SSOProviderType.GOOGLE_OAUTH)
    client = oidc_multi._build_client(provider, dict(_GOOGLE_CONFIG))
    assert client.name == "google"


def test_build_client_oidc_uses_provider_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # VerifiedEmailOpenID.__init__ fetches the discovery doc over the network.
    # Stub it so the unit test stays offline.
    def _fake_openid(
        _client_id: str,
        _client_secret: str,
        _config_url: str,
        *,
        name: str,
        **_kwargs: Any,
    ) -> Any:
        return SimpleNamespace(name=name)

    monkeypatch.setattr(oidc_multi, "VerifiedEmailOpenID", _fake_openid)
    client = oidc_multi._build_client(_provider(name="okta"), dict(_OIDC_CONFIG))
    assert client.name == "okta"


@pytest.mark.asyncio
async def test_client_cache_hits_and_rebuilds_on_config_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oidc_multi._CLIENT_CACHE.clear()
    builds = {"count": 0}

    def _fake_build(provider: SSOProvider, _config: dict[str, Any]) -> Any:
        builds["count"] += 1
        return SimpleNamespace(name=provider.name)

    monkeypatch.setattr(oidc_multi, "_build_client", _fake_build)
    provider = _provider()

    await oidc_multi._get_oauth_client(provider, dict(_OIDC_CONFIG))
    await oidc_multi._get_oauth_client(provider, dict(_OIDC_CONFIG))
    assert builds["count"] == 1  # same key is a cache hit

    # A rotated secret changes the config hash, so the key changes and rebuilds.
    await oidc_multi._get_oauth_client(
        provider, {**_OIDC_CONFIG, "client_secret": "rotated"}
    )
    assert builds["count"] == 2
    oidc_multi._CLIENT_CACHE.clear()


def test_decode_state_accepts_valid() -> None:
    csrf = generate_csrf_token()
    state = generate_state_token(
        {"next_url": "/", "provider_name": "okta", CSRF_TOKEN_KEY: csrf}, _TEST_SECRET
    )
    request = cast(Any, SimpleNamespace(cookies={CSRF_TOKEN_COOKIE_NAME: csrf}))
    data = decode_and_validate_oauth_state(
        request=request,
        state_value=state,
        state_secret=_TEST_SECRET,
        expected_provider_name="okta",
    )
    assert data[CSRF_TOKEN_KEY] == csrf


def test_decode_state_rejects_mismatched_csrf() -> None:
    csrf = generate_csrf_token()
    state = generate_state_token(
        {"next_url": "/", "provider_name": "okta", CSRF_TOKEN_KEY: csrf}, _TEST_SECRET
    )
    request = cast(Any, SimpleNamespace(cookies={CSRF_TOKEN_COOKIE_NAME: "different"}))
    with pytest.raises(OnyxError):
        decode_and_validate_oauth_state(
            request=request,
            state_value=state,
            state_secret=_TEST_SECRET,
            expected_provider_name="okta",
        )


def test_decode_state_rejects_wrong_provider() -> None:
    # A state minted for one provider must not validate on another's callback.
    csrf = generate_csrf_token()
    state = generate_state_token(
        {"next_url": "/", "provider_name": "okta", CSRF_TOKEN_KEY: csrf}, _TEST_SECRET
    )
    request = cast(Any, SimpleNamespace(cookies={CSRF_TOKEN_COOKIE_NAME: csrf}))
    with pytest.raises(OnyxError):
        decode_and_validate_oauth_state(
            request=request,
            state_value=state,
            state_secret=_TEST_SECRET,
            expected_provider_name="google",
        )


def test_decode_state_rejects_bad_jwt() -> None:
    request = cast(Any, SimpleNamespace(cookies={CSRF_TOKEN_COOKIE_NAME: "x"}))
    with pytest.raises(OnyxError):
        decode_and_validate_oauth_state(
            request=request,
            state_value="not-a-jwt",
            state_secret=_TEST_SECRET,
            expected_provider_name="okta",
        )


# ---------------------------------------------------------------------------
# Legacy callback routing: migrated rows keep the redirect URI their IdP
# client already allowlists, so upgrading never requires an IdP console edit.
# ---------------------------------------------------------------------------


def test_callback_uri_parametric_by_default() -> None:
    provider = _provider()
    assert oidc_multi._callback_uri(provider, dict(_OIDC_CONFIG)).endswith(
        "/api/auth/oidc/okta/callback"
    )


def test_callback_uri_legacy_oidc() -> None:
    provider = _provider()
    config: dict[str, object] = {**_OIDC_CONFIG, "legacy_callback": True}
    uri = oidc_multi._callback_uri(provider, config)
    assert uri.endswith("/auth/oidc/callback")
    assert "/api/" not in uri


def test_callback_uri_legacy_google() -> None:
    provider = _provider(name="google", provider_type=SSOProviderType.GOOGLE_OAUTH)
    config: dict[str, object] = {**_GOOGLE_CONFIG, "legacy_callback": True}
    uri = oidc_multi._callback_uri(provider, config)
    assert uri.endswith("/auth/oauth/callback")
    assert "/api/" not in uri


def test_validate_config_accepts_legacy_callback_for_oauth_types() -> None:
    from onyx.db.sso_provider import validate_sso_config

    oidc = validate_sso_config(
        SSOProviderType.OIDC, {**_OIDC_CONFIG, "legacy_callback": True}
    )
    assert oidc["legacy_callback"] is True
    google = validate_sso_config(
        SSOProviderType.GOOGLE_OAUTH, {**_GOOGLE_CONFIG, "legacy_callback": True}
    )
    assert google["legacy_callback"] is True
    # Omitting the flag stays valid and defaults off.
    assert (
        validate_sso_config(SSOProviderType.OIDC, dict(_OIDC_CONFIG))["legacy_callback"]
        is False
    )


def test_validate_config_rejects_legacy_callback_for_saml() -> None:
    from onyx.db.sso_provider import validate_sso_config

    with pytest.raises(ValueError):
        validate_sso_config(
            SSOProviderType.SAML,
            {
                "idp_entity_id": "e",
                "idp_sso_url": "https://idp/sso",
                "idp_x509_cert": "cert",
                "sp_entity_id": "sp",
                "legacy_callback": True,
            },
        )


def test_login_callback_uri_saml_is_fixed_acs() -> None:
    from onyx.db.sso_provider import sso_login_callback_uri

    provider = _provider(name="corp-saml", provider_type=SSOProviderType.SAML)
    uri = sso_login_callback_uri(provider, {}, "https://onyx.example.com")
    assert uri == "https://onyx.example.com/api/auth/saml/callback"


def test_fixed_callback_rejects_missing_state() -> None:
    import asyncio

    request = cast(Any, SimpleNamespace(cookies={}))
    with pytest.raises(OnyxError):
        asyncio.run(
            oidc_multi.oidc_login_callback(
                request=request,
                code="code",
                state=None,
                error=None,
                db_session=_DB,
                strategy=cast(Any, None),
                user_manager=cast(Any, None),
            )
        )


def test_fixed_callback_rejects_state_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setattr(oidc_multi, "USER_AUTH_SECRET", _TEST_SECRET)
    csrf = generate_csrf_token()
    state = generate_state_token({"next_url": "/", CSRF_TOKEN_KEY: csrf}, _TEST_SECRET)
    request = cast(Any, SimpleNamespace(cookies={CSRF_TOKEN_COOKIE_NAME: csrf}))
    with pytest.raises(OnyxError):
        asyncio.run(
            oidc_multi.oidc_login_callback(
                request=request,
                code="code",
                state=state,
                error=None,
                db_session=_DB,
                strategy=cast(Any, None),
                user_manager=cast(Any, None),
            )
        )
