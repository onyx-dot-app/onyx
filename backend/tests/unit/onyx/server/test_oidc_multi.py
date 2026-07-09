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
    assert config == dict(_OIDC_CONFIG)


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
    assert config == dict(_GOOGLE_CONFIG)


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
