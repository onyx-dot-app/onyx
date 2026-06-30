"""The HubSpot provider's credential extraction, focused on persisting the
per-user granted scopes (ENG-4261).

With `optional_scope` (ENG-4260) different users grant different scope sets, so
on the OAuth callback we read HubSpot's token-info endpoint and persist the
actually-granted scopes under `granted_scopes` alongside the credential. The
lookup is strictly best-effort: a failure must never break the connect flow."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers import hubspot as hubspot_module
from onyx.external_apps.providers.hubspot import HubspotProvider

_TOKEN_RESPONSE: dict[str, Any] = {
    "access_token": "at-123",
    "token_type": "bearer",
    "refresh_token": "rt-456",
    "expires_in": 1800,
}

_GRANTED_SCOPES = [
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
]


def _token_info_response(status_code: int, body: Any) -> requests.Response:
    """A real `requests.Response` whose `.json()` returns `body`, mimicking the
    HubSpot token-info endpoint."""
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _patch_token_info(
    monkeypatch: pytest.MonkeyPatch, response_or_exc: object
) -> dict[str, Any]:
    """Patch the token-info GET. If `response_or_exc` is an Exception, raising it;
    otherwise returning it. Captures the URL the provider requested."""
    captured: dict[str, Any] = {}

    def _get(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        if isinstance(response_or_exc, Exception):
            raise response_or_exc
        return response_or_exc

    monkeypatch.setattr(hubspot_module.requests, "get", _get)
    return captured


def test_extract_credentials_persists_granted_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a successful token-info lookup the granted scopes are persisted
    alongside the access token (and the other credential fields)."""
    captured = _patch_token_info(
        monkeypatch, _token_info_response(200, {"scopes": _GRANTED_SCOPES})
    )

    creds = HubspotProvider().extract_credentials(_TOKEN_RESPONSE)

    assert creds["access_token"] == "at-123"
    assert creds["refresh_token"] == "rt-456"
    assert creds["expires_in"] == 1800
    assert creds["granted_scopes"] == _GRANTED_SCOPES
    # The token-info endpoint is addressed by the access token in the path.
    assert captured["url"].endswith("/oauth/v1/access-tokens/at-123")


def test_extract_credentials_no_token_info_call_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network error talking to the token-info endpoint must NOT break connect:
    the access token is still returned and `granted_scopes` is simply absent."""
    _patch_token_info(monkeypatch, requests.ConnectionError("connection reset"))

    creds = HubspotProvider().extract_credentials(_TOKEN_RESPONSE)

    assert creds["access_token"] == "at-123"
    assert "granted_scopes" not in creds


def test_extract_credentials_http_error_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-2xx from the token-info endpoint (raise_for_status) is swallowed."""
    _patch_token_info(monkeypatch, _token_info_response(401, {"message": "expired"}))

    creds = HubspotProvider().extract_credentials(_TOKEN_RESPONSE)

    assert creds["access_token"] == "at-123"
    assert "granted_scopes" not in creds


def test_extract_credentials_missing_scopes_field_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 token-info body without a `scopes` list yields no granted scopes,
    but still does not raise."""
    _patch_token_info(monkeypatch, _token_info_response(200, {"hub_id": 42}))

    creds = HubspotProvider().extract_credentials(_TOKEN_RESPONSE)

    assert creds["access_token"] == "at-123"
    assert "granted_scopes" not in creds


def test_extract_credentials_missing_access_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent access token is a hard error — and we never attempt the
    token-info lookup."""

    def _boom(*_a: Any, **_k: Any) -> object:
        raise AssertionError("token-info must not be called without an access token")

    monkeypatch.setattr(hubspot_module.requests, "get", _boom)

    with pytest.raises(OnyxError):
        HubspotProvider().extract_credentials({"token_type": "bearer"})
