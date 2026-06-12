"""Admin-defined custom OAuth: config validation, the config-driven handler's
URL/exchange/refresh behavior, handler resolution, and the OAuth-mode auth
template validation."""

import json
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
import requests
from pydantic import ValidationError

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import validate_oauth_auth_template
from onyx.db.models import ExternalApp
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.custom_oauth import CustomOAuthConfig
from onyx.external_apps.custom_oauth import CustomOAuthHandler
from onyx.external_apps.oauth_handler import TokenEndpointAuthMethod
from onyx.external_apps.oauth_handler import TokenRequestTransientError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import resolve_oauth_handler


def _config(**overrides: Any) -> CustomOAuthConfig:
    base: dict[str, Any] = {
        "authorize_url": "https://idp.example.com/oauth/authorize",
        "token_url": "https://idp.example.com/oauth/token",
    }
    return CustomOAuthConfig(**{**base, **overrides})


def _response(status_code: int, body: Any) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _capturing_post(
    monkeypatch: pytest.MonkeyPatch, response: requests.Response
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> requests.Response:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["headers"] = kwargs.get("headers")
        return response

    monkeypatch.setattr("onyx.external_apps.oauth_handler.requests.post", _post)
    return captured


# ---------------------------------------------------------------------------
# CustomOAuthConfig validation
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    config = _config()
    assert config.scope == ""
    assert config.scope_param == "scope"
    assert config.extra_authorize_params == {}
    assert (
        config.token_endpoint_auth_method == TokenEndpointAuthMethod.CLIENT_SECRET_POST
    )


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://idp.example.com/authorize",  # not https
        "idp.example.com/authorize",  # not absolute
        "https://user:pass@idp.example.com/authorize",  # userinfo
        "https://",  # no host
    ],
)
@pytest.mark.parametrize("field", ["authorize_url", "token_url"])
def test_config_rejects_bad_urls(field: str, bad_url: str) -> None:
    with pytest.raises(ValidationError):
        _config(**{field: bad_url})


def test_config_rejects_blank_scope_param() -> None:
    with pytest.raises(ValidationError):
        _config(scope_param="  ")


def test_config_rejects_unknown_fields() -> None:
    # extra="forbid" so an admin's typo'd key fails loudly instead of being
    # silently dropped.
    with pytest.raises(ValidationError):
        _config(authorize_uri="https://idp.example.com/authorize")


# ---------------------------------------------------------------------------
# Authorize URL construction
# ---------------------------------------------------------------------------


def _authorize_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_authorize_url_includes_flow_params() -> None:
    handler = CustomOAuthHandler(_config(scope="read write"))
    url = handler.build_authorize_url(
        client_id="cid", redirect_uri="https://onyx.example.com/cb", state="st"
    )
    assert url.startswith("https://idp.example.com/oauth/authorize?")
    params = _authorize_params(url)
    assert params["client_id"] == ["cid"]
    assert params["redirect_uri"] == ["https://onyx.example.com/cb"]
    assert params["scope"] == ["read write"]
    assert params["state"] == ["st"]
    # RFC 6749 §4.1.1 — always sent even though the admin configured nothing.
    assert params["response_type"] == ["code"]


def test_authorize_url_omits_empty_scope() -> None:
    handler = CustomOAuthHandler(_config())
    url = handler.build_authorize_url(
        client_id="cid", redirect_uri="https://onyx.example.com/cb", state="st"
    )
    assert "scope" not in _authorize_params(url)


def test_authorize_url_custom_scope_param_and_extra_params() -> None:
    handler = CustomOAuthHandler(
        _config(
            scope="users:read",
            scope_param="user_scope",
            extra_authorize_params={"access_type": "offline"},
        )
    )
    params = _authorize_params(
        handler.build_authorize_url(
            client_id="cid", redirect_uri="https://onyx.example.com/cb", state="st"
        )
    )
    assert params["user_scope"] == ["users:read"]
    assert params["access_type"] == ["offline"]
    assert params["response_type"] == ["code"]


@pytest.mark.parametrize(
    "param", ["response_type", "client_id", "redirect_uri", "state"]
)
def test_config_rejects_reserved_authorize_params(param: str) -> None:
    """Reserved protocol params are rejected at write time — e.g. a `state`
    override would disable the callback's CSRF protection."""
    with pytest.raises(ValidationError):
        _config(extra_authorize_params={param: "x"})


# ---------------------------------------------------------------------------
# Code exchange + refresh through the shared token request
# ---------------------------------------------------------------------------


def test_exchange_posts_client_credentials_in_body_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capturing_post(
        monkeypatch,
        _response(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "token_type": "bearer",
            },
        ),
    )
    creds = CustomOAuthHandler(_config()).exchange_authorization_code(
        code="c0de",
        redirect_uri="https://onyx.example.com/cb",
        client_id="cid",
        client_secret="secret",
    )
    assert captured["url"] == "https://idp.example.com/oauth/token"
    assert captured["data"] == {
        "grant_type": "authorization_code",
        "code": "c0de",
        "redirect_uri": "https://onyx.example.com/cb",
        "client_id": "cid",
        "client_secret": "secret",
    }
    assert "Authorization" not in captured["headers"]
    assert creds["access_token"] == "at"
    assert creds["refresh_token"] == "rt"
    assert creds["expires_in"] == 3600


def test_exchange_keeps_zero_expires_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """`expires_in: 0` means already-expired — dropping it would read as a
    never-expiring token and suppress refresh."""
    _capturing_post(
        monkeypatch,
        _response(200, {"access_token": "at", "expires_in": 0}),
    )
    creds = CustomOAuthHandler(_config()).exchange_authorization_code(
        code="c0de",
        redirect_uri="https://onyx.example.com/cb",
        client_id="cid",
        client_secret="secret",
    )
    assert creds["expires_in"] == 0


def test_exchange_with_basic_auth_sends_header_not_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capturing_post(monkeypatch, _response(200, {"access_token": "at"}))
    CustomOAuthHandler(
        _config(token_endpoint_auth_method=TokenEndpointAuthMethod.CLIENT_SECRET_BASIC)
    ).exchange_authorization_code(
        code="c0de",
        redirect_uri="https://onyx.example.com/cb",
        client_id="cid",
        client_secret="secret",
    )
    # b64("cid:secret")
    assert captured["headers"]["Authorization"] == "Basic Y2lkOnNlY3JldA=="
    assert "client_id" not in captured["data"]
    assert "client_secret" not in captured["data"]


def test_basic_auth_form_encodes_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RFC 6749 §2.3.1: each credential is form-urlencoded before the
    `id:secret` join."""
    captured = _capturing_post(monkeypatch, _response(200, {"access_token": "at"}))
    CustomOAuthHandler(
        _config(token_endpoint_auth_method=TokenEndpointAuthMethod.CLIENT_SECRET_BASIC)
    ).exchange_authorization_code(
        code="c0de",
        redirect_uri="https://onyx.example.com/cb",
        client_id="c:id",
        client_secret="s ecret&",
    )
    # b64("c%3Aid:s+ecret%26")
    assert captured["headers"]["Authorization"] == "Basic YyUzQWlkOnMrZWNyZXQlMjY="


def test_exchange_missing_access_token_raises_onyx_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capturing_post(monkeypatch, _response(200, {"token_type": "bearer"}))
    with pytest.raises(OnyxError):
        CustomOAuthHandler(_config()).exchange_authorization_code(
            code="c",
            redirect_uri="https://o.example.com/cb",
            client_id="i",
            client_secret="s",
        )


def test_exchange_provider_error_raises_token_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capturing_post(monkeypatch, _response(400, {"error": "invalid_request"}))
    with pytest.raises(TokenRequestTransientError):
        CustomOAuthHandler(_config()).exchange_authorization_code(
            code="c",
            redirect_uri="https://o.example.com/cb",
            client_id="i",
            client_secret="s",
        )


def test_refresh_uses_basic_auth_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both grants go through the same token-request helper, so the configured
    client-auth method applies to refresh too."""
    captured = _capturing_post(monkeypatch, _response(200, {"access_token": "new"}))
    refreshed = CustomOAuthHandler(
        _config(token_endpoint_auth_method=TokenEndpointAuthMethod.CLIENT_SECRET_BASIC)
    ).refresh_credentials(
        {"access_token": "old", "refresh_token": "rt"}, "cid", "secret"
    )
    assert captured["headers"]["Authorization"] == "Basic Y2lkOnNlY3JldA=="
    assert captured["data"] == {"grant_type": "refresh_token", "refresh_token": "rt"}
    assert refreshed["access_token"] == "new"
    assert refreshed["refresh_token"] == "rt"  # carried forward via the merge


# ---------------------------------------------------------------------------
# Handler resolution (the single auth-mechanism predicate)
# ---------------------------------------------------------------------------


def test_resolve_built_in_oauth_app_returns_registered_provider() -> None:
    app = ExternalApp(app_type=ExternalAppType.SLACK)
    handler = resolve_oauth_handler(app)
    assert isinstance(handler, OAuthExternalAppProvider)
    assert handler.spec.app_type == ExternalAppType.SLACK


def test_resolve_custom_app_with_config_returns_custom_handler() -> None:
    app = ExternalApp(
        app_type=ExternalAppType.CUSTOM,
        oauth_config=_config().model_dump(mode="json"),
    )
    handler = resolve_oauth_handler(app)
    assert isinstance(handler, CustomOAuthHandler)
    assert handler.oauth.token_url == "https://idp.example.com/oauth/token"


def test_resolve_custom_app_without_config_is_none() -> None:
    assert (
        resolve_oauth_handler(
            ExternalApp(app_type=ExternalAppType.CUSTOM, oauth_config=None)
        )
        is None
    )


@pytest.mark.parametrize(
    "corrupt_config",
    [
        {"authorize_url": "nope"},  # invalid field values
        {},  # falsy but not None — corruption, not a static app
    ],
)
def test_resolve_corrupt_stored_config_fails_loudly(
    corrupt_config: dict[str, str],
) -> None:
    # Writes are validated, so a corrupt stored config is a bug — surfaced,
    # not masked as "non-OAuth app". Only None means static.
    app = ExternalApp(app_type=ExternalAppType.CUSTOM, oauth_config=corrupt_config)
    with pytest.raises(ValidationError):
        resolve_oauth_handler(app)


# ---------------------------------------------------------------------------
# OAuth-mode auth template validation
# ---------------------------------------------------------------------------


def test_oauth_template_requires_access_token_placeholder() -> None:
    with pytest.raises(OnyxError):
        validate_oauth_auth_template({"Authorization": "Bearer {api_key}"}, {})
    with pytest.raises(OnyxError):
        validate_oauth_auth_template({}, {})


def test_oauth_template_rejects_access_token_as_org_credential() -> None:
    with pytest.raises(OnyxError):
        validate_oauth_auth_template(
            {"Authorization": "Bearer {access_token}"}, {"access_token": "static"}
        )


def test_oauth_template_rejects_unfillable_placeholder() -> None:
    with pytest.raises(OnyxError):
        validate_oauth_auth_template(
            {"Authorization": "Bearer {access_token}", "X-Key": "{api_key}"}, {}
        )


def test_oauth_template_allows_org_filled_placeholders() -> None:
    validate_oauth_auth_template(
        {"Authorization": "Bearer {access_token}", "X-Tenant": "{tenant_id}"},
        {"tenant_id": "t-1"},
    )
