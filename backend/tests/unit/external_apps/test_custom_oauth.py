"""Admin-defined OAuth for CUSTOM external apps: config validation, the
config-driven handler (authorize URL, token exchange, refresh, client auth),
registry resolution, and the auth-template invariants."""

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from pydantic import ValidationError

from onyx.db.enums import ExternalAppType
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.custom_oauth import (
    CustomOAuthConfig,
    CustomOAuthHandler,
    validate_custom_oauth_app,
)
from onyx.external_apps.providers.base import (
    OAuthFlowHandler,
    TokenEndpointAuthMethod,
    TokenRefreshTerminalError,
    TokenRefreshTransientError,
)
from onyx.external_apps.providers.github import GitHubProvider
from onyx.external_apps.providers.registry import resolve_oauth_handler

_AUTHORIZE = "https://auth.example.com/oauth/authorize"
_TOKEN = "https://auth.example.com/oauth/token"


def _config(**overrides: Any) -> CustomOAuthConfig:
    base: dict[str, Any] = {
        "authorize_url": _AUTHORIZE,
        "token_url": _TOKEN,
        "scopes": ["read", "write"],
    }
    base.update(overrides)
    return CustomOAuthConfig.model_validate(base)


def _response(status_code: int, body: Any) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


class _App:
    """Duck-typed ExternalApp row (only what resolve_oauth_handler reads)."""

    def __init__(self, app_type: ExternalAppType, oauth_config: Any = None) -> None:
        self.app_type = app_type
        self.oauth_config = oauth_config
        self.name = "app"


# ---------------------------------------------------------------------------
# CustomOAuthConfig validation
# ---------------------------------------------------------------------------


def test_config_defaults_and_scope_join() -> None:
    cfg = _config()
    assert cfg.scope == "read write"
    assert cfg.scope_param == "scope"
    assert cfg.token_endpoint_auth_method is TokenEndpointAuthMethod.CLIENT_SECRET_POST
    assert cfg.extra_authorize_params == {}


def test_config_comma_delimiter_and_scope_cleanup() -> None:
    cfg = _config(scopes=[" read ", "", "read", "write"], scope_delimiter=",")
    assert cfg.scopes == ["read", "write"]
    assert cfg.scope == "read,write"


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.example.com/authorize",
        "auth.example.com/authorize",
        "https://user:pw@auth.example.com/authorize",
        "https://auth.example.com/authorize#frag",
        "",
    ],
)
def test_config_rejects_bad_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        _config(authorize_url=url)
    with pytest.raises(ValidationError):
        _config(token_url=url)


@pytest.mark.parametrize(
    "param", ["response_type", "client_id", "redirect_uri", "state", "scope"]
)
def test_config_rejects_reserved_extra_params(param: str) -> None:
    with pytest.raises(ValidationError):
        _config(extra_authorize_params={param: "x"})


def test_config_rejects_unknown_fields_and_whitespace_scopes() -> None:
    with pytest.raises(ValidationError):
        _config(client_secret="leak")  # secrets never live in the config
    with pytest.raises(ValidationError):
        _config(scopes=["read write"])
    with pytest.raises(ValidationError):
        _config(scope_delimiter=";")


def test_config_round_trips_through_json() -> None:
    cfg = _config(
        extra_authorize_params={"access_type": "offline"},
        token_endpoint_auth_method="client_secret_basic",
    )
    dumped = cfg.model_dump(mode="json")
    assert dumped["token_endpoint_auth_method"] == "client_secret_basic"
    assert CustomOAuthConfig.model_validate(dumped) == cfg


# ---------------------------------------------------------------------------
# CustomOAuthHandler: authorize URL
# ---------------------------------------------------------------------------


def test_handler_is_flow_handler() -> None:
    assert isinstance(CustomOAuthHandler(_config()), OAuthFlowHandler)


def test_authorize_url_contains_protocol_params_and_scopes() -> None:
    handler = CustomOAuthHandler(
        _config(extra_authorize_params={"access_type": "offline", "prompt": "consent"})
    )
    url = handler.build_authorize_url(
        client_id="cid", redirect_uri="https://onyx.example/cb", state="st"
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == _AUTHORIZE
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["cid"]
    assert qs["redirect_uri"] == ["https://onyx.example/cb"]
    assert qs["state"] == ["st"]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["read write"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]


def test_authorize_url_omits_scope_when_empty_and_honours_scope_param() -> None:
    no_scope = CustomOAuthHandler(_config(scopes=[])).build_authorize_url(
        client_id="c", redirect_uri="https://o/cb", state="s"
    )
    assert "scope" not in parse_qs(urlparse(no_scope).query)

    user_scope = CustomOAuthHandler(
        _config(scope_param="user_scope")
    ).build_authorize_url(client_id="c", redirect_uri="https://o/cb", state="s")
    qs = parse_qs(urlparse(user_scope).query)
    assert qs["user_scope"] == ["read write"]
    assert "scope" not in qs


# ---------------------------------------------------------------------------
# CustomOAuthHandler: token exchange request + client auth methods
# ---------------------------------------------------------------------------


def test_token_exchange_request_client_secret_post() -> None:
    req = CustomOAuthHandler(_config()).build_token_exchange_request(
        "code123", "cid", "sec", "https://o/cb"
    )
    assert req.json_encoded is False
    assert req.body == {
        "grant_type": "authorization_code",
        "code": "code123",
        "redirect_uri": "https://o/cb",
        "client_id": "cid",
        "client_secret": "sec",
    }
    assert "Authorization" not in req.headers
    assert req.headers["Accept"] == "application/json"


def test_token_exchange_request_client_secret_basic() -> None:
    handler = CustomOAuthHandler(
        _config(token_endpoint_auth_method="client_secret_basic")
    )
    req = handler.build_token_exchange_request("code123", "ci:d", "s c", "https://o/cb")
    assert "client_id" not in req.body and "client_secret" not in req.body
    assert req.body["grant_type"] == "authorization_code"
    scheme, _, b64 = req.headers["Authorization"].partition(" ")
    assert scheme == "Basic"
    # RFC 6749 §2.3.1: each part form-encoded before the join.
    assert base64.b64decode(b64).decode() == "ci%3Ad:s+c"


def test_extract_credentials_plain_rfc6749() -> None:
    handler = CustomOAuthHandler(_config())
    creds = handler.extract_credentials(
        {
            "access_token": "at",
            "token_type": "Bearer",
            "scope": "read",
            "refresh_token": "rt",
            "expires_in": 0,
            "id_token": "ignored",
        }
    )
    assert creds == {
        "access_token": "at",
        "token_type": "Bearer",
        "scope": "read",
        "refresh_token": "rt",
        "expires_in": 0,  # presence, not truthiness
    }
    assert handler.extract_credentials({"access_token": "at"}) == {"access_token": "at"}
    assert handler.extract_granted_scopes({"scope": "read write"}) == ["read", "write"]


def test_extract_credentials_requires_access_token() -> None:
    with pytest.raises(OnyxError):
        CustomOAuthHandler(_config()).extract_credentials({"token_type": "Bearer"})


# ---------------------------------------------------------------------------
# CustomOAuthHandler: refresh (mocked HTTP)
# ---------------------------------------------------------------------------


def _capture_post(monkeypatch: pytest.MonkeyPatch, response: requests.Response) -> dict:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> requests.Response:
        captured["url"] = url
        captured.update(kwargs)
        return response

    monkeypatch.setattr("onyx.external_apps.providers.base.requests.post", fake_post)
    return captured


def test_refresh_posts_to_token_url_and_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_post(
        monkeypatch, _response(200, {"access_token": "new", "expires_in": 3600})
    )
    result = CustomOAuthHandler(_config()).refresh_credentials(
        {"access_token": "old", "refresh_token": "rt", "scope": "read"}, "cid", "sec"
    )
    assert captured["url"] == _TOKEN
    assert captured["data"] == {
        "grant_type": "refresh_token",
        "client_id": "cid",
        "client_secret": "sec",
        "refresh_token": "rt",
    }
    assert result["access_token"] == "new"
    assert result["expires_in"] == 3600
    assert result["refresh_token"] == "rt"  # carried forward
    assert result["scope"] == "read"  # connect-time field survives
    assert "expires_at" not in result  # clockless


def test_refresh_uses_basic_auth_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_post(monkeypatch, _response(200, {"access_token": "new"}))
    handler = CustomOAuthHandler(
        _config(token_endpoint_auth_method="client_secret_basic")
    )
    handler.refresh_credentials({"refresh_token": "rt"}, "cid", "sec")
    assert captured["headers"]["Authorization"] == (
        "Basic " + base64.b64encode(b"cid:sec").decode()
    )
    assert captured["data"] == {"grant_type": "refresh_token", "refresh_token": "rt"}


def test_refresh_errors_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = CustomOAuthHandler(_config())
    with pytest.raises(TokenRefreshTerminalError):
        handler.refresh_credentials({"access_token": "only"}, "cid", "sec")

    _capture_post(monkeypatch, _response(400, {"error": "invalid_grant"}))
    with pytest.raises(TokenRefreshTerminalError):
        handler.refresh_credentials({"refresh_token": "rt"}, "cid", "sec")

    _capture_post(monkeypatch, _response(503, {"error": "temporarily_unavailable"}))
    with pytest.raises(TokenRefreshTransientError):
        handler.refresh_credentials({"refresh_token": "rt"}, "cid", "sec")

    # 2xx body without an access token → transient, keep the existing token.
    _capture_post(monkeypatch, _response(200, {"token_type": "Bearer"}))
    with pytest.raises(TokenRefreshTransientError):
        handler.refresh_credentials({"refresh_token": "rt"}, "cid", "sec")


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------


def test_resolve_oauth_handler_dispatch() -> None:
    custom_static = _App(ExternalAppType.CUSTOM, None)
    assert resolve_oauth_handler(custom_static) is None  # type: ignore[arg-type]

    custom_oauth = _App(ExternalAppType.CUSTOM, _config().model_dump(mode="json"))
    handler = resolve_oauth_handler(custom_oauth)  # type: ignore[arg-type]
    assert isinstance(handler, CustomOAuthHandler)
    assert handler.oauth.token_url == _TOKEN

    built_in = resolve_oauth_handler(_App(ExternalAppType.GITHUB))  # type: ignore[arg-type]
    assert isinstance(built_in, GitHubProvider)
    assert built_in.oauth is GitHubProvider.spec.oauth


def test_resolve_oauth_handler_surfaces_corrupt_config() -> None:
    corrupt = _App(ExternalAppType.CUSTOM, {"authorize_url": "nope"})
    with pytest.raises(ValidationError):
        resolve_oauth_handler(corrupt)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Built-in providers still behave after the OAuthFlowHandler extraction
# ---------------------------------------------------------------------------


def test_built_in_authorize_url_unchanged() -> None:
    url = GitHubProvider().build_authorize_url(
        client_id="cid", redirect_uri="https://o/cb", state="st"
    )
    qs = parse_qs(urlparse(url).query)
    assert qs["scope"] == [GitHubProvider.spec.oauth.scope]
    assert qs["client_id"] == ["cid"]
    assert "response_type" not in qs  # built-ins keep their exact prior params


# ---------------------------------------------------------------------------
# validate_custom_oauth_app
# ---------------------------------------------------------------------------

_ORG = {"client_id": "cid", "client_secret": "sec"}
_TEMPLATE = {"Authorization": "Bearer {access_token}"}


def _validate(template: dict[str, Any], org: dict[str, Any]) -> None:
    from onyx.db.external_app import placeholders_in_template

    validate_custom_oauth_app(org, placeholders=placeholders_in_template(template))


def test_validate_custom_oauth_app_accepts_bearer_template() -> None:
    _validate(_TEMPLATE, _ORG)
    # Extra org-filled placeholder is fine.
    _validate(
        {"Authorization": "Bearer {access_token}", "X-Org": "{org_id}"},
        {**_ORG, "org_id": "o"},
    )


@pytest.mark.parametrize(
    ("template", "org"),
    [
        (_TEMPLATE, {"client_id": "cid"}),  # missing client_secret
        (_TEMPLATE, {"client_id": "", "client_secret": "s"}),  # blank client_id
        ({"Authorization": "Bearer {token}"}, _ORG),  # no {access_token}
        (_TEMPLATE, {**_ORG, "access_token": "static"}),  # org-filled token
        ({"Authorization": "Bearer {access_token}", "X-Key": "{api_key}"}, _ORG),
    ],
)
def test_validate_custom_oauth_app_rejects(template: dict, org: dict) -> None:
    with pytest.raises(OnyxError):
        _validate(template, org)
