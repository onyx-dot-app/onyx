"""Providers like Google issue refresh tokens only when the authorize request
asks for offline access; these params must be injected into every flow."""

from urllib.parse import parse_qs, urlparse

from onyx.auth.oauth_token_manager import (
    OAuthFlowParams,
    build_oauth_authorization_url,
    ensure_offline_access_auth_params,
)

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_google_prebuilt_url_gains_offline_access_params() -> None:
    url = ensure_offline_access_auth_params(
        f"{_GOOGLE_AUTH_ENDPOINT}?client_id=x&state=s&code_challenge=c"
    )
    query = _query(url)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    # Existing params survive the rewrite.
    assert query["client_id"] == ["x"]
    assert query["state"] == ["s"]
    assert query["code_challenge"] == ["c"]


def test_prebuilt_url_existing_params_win() -> None:
    url = ensure_offline_access_auth_params(
        f"{_GOOGLE_AUTH_ENDPOINT}?client_id=x&prompt=none"
    )
    query = _query(url)
    assert query["prompt"] == ["none"]
    assert query["access_type"] == ["offline"]


def test_non_google_prebuilt_url_unchanged() -> None:
    url = "https://example.com/authorize?client_id=x"
    assert ensure_offline_access_auth_params(url) == url


def test_build_authorization_url_adds_google_offline_access() -> None:
    url = build_oauth_authorization_url(
        OAuthFlowParams(
            authorization_url=_GOOGLE_AUTH_ENDPOINT,
            token_url="https://oauth2.googleapis.com/token",
            client_id="x",
        ),
        redirect_uri="https://app.example.com/callback",
        state="s",
    )
    query = _query(url)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


def test_build_authorization_url_additional_params_override_defaults() -> None:
    url = build_oauth_authorization_url(
        OAuthFlowParams(
            authorization_url=_GOOGLE_AUTH_ENDPOINT,
            token_url="https://oauth2.googleapis.com/token",
            client_id="x",
            additional_params={"prompt": "select_account"},
        ),
        redirect_uri="https://app.example.com/callback",
        state="s",
    )
    query = _query(url)
    assert query["prompt"] == ["select_account"]
    assert query["access_type"] == ["offline"]


def test_build_authorization_url_endpoint_embedded_params_win() -> None:
    url = build_oauth_authorization_url(
        OAuthFlowParams(
            authorization_url=f"{_GOOGLE_AUTH_ENDPOINT}?prompt=select_account",
            token_url="https://oauth2.googleapis.com/token",
            client_id="x",
        ),
        redirect_uri="https://app.example.com/callback",
        state="s",
    )
    query = _query(url)
    assert query["prompt"] == ["select_account"]
    assert query["access_type"] == ["offline"]


def test_build_authorization_url_non_google_untouched() -> None:
    url = build_oauth_authorization_url(
        OAuthFlowParams(
            authorization_url="https://example.com/authorize",
            token_url="https://example.com/token",
            client_id="x",
        ),
        redirect_uri="https://app.example.com/callback",
        state="s",
    )
    query = _query(url)
    assert "access_type" not in query
    assert "prompt" not in query
