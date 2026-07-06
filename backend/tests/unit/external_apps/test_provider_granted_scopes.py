"""Per-provider granted-scope extraction (ENG-4261).

On the OAuth callback each provider derives the scopes the user actually
granted, persisted onto ``ExternalAppUserCredential.granted_scopes`` for
downstream action gating. Most providers echo the RFC 6749 ``scope`` field and
inherit the base default; only Slack (nested) and HubSpot (out-of-band lookup)
override. A signal we can't read is recorded as ``None`` — never an empty
grant."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers import hubspot as hubspot_module
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import parse_granted_scopes
from onyx.external_apps.providers.hubspot import HubspotProvider
from onyx.external_apps.providers.registry import PROVIDERS


def _oauth_provider(app_type: ExternalAppType) -> OAuthExternalAppProvider:
    provider = PROVIDERS[app_type]
    assert isinstance(provider, OAuthExternalAppProvider)
    return provider


# --- parse_granted_scopes: the shared, delimiter-tolerant normaliser ---------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a b c", ["a", "b", "c"]),  # RFC 6749 space-delimited
        ("a,b,c", ["a", "b", "c"]),  # comma-delimited (GitHub, Slack)
        ("  a   b,c ,, ", ["a", "b", "c"]),  # mixed delimiters + empties dropped
        (["a", " b ", "c"], ["a", "b", "c"]),  # already tokenised
        ("single", ["single"]),
    ],
)
def test_parse_granted_scopes_parses(raw: Any, expected: list[str]) -> None:
    assert parse_granted_scopes(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", ",, ", [], ["", "  "], 42, {}])
def test_parse_granted_scopes_absent_is_none(raw: Any) -> None:
    """An absent/empty signal is None (grant unknown), never an empty list."""
    assert parse_granted_scopes(raw) is None


# --- Default: providers that echo the top-level `scope` field ----------------


def test_github_default_reads_comma_delimited_scope() -> None:
    granted = _oauth_provider(ExternalAppType.GITHUB).extract_granted_scopes(
        {"access_token": "at", "scope": "repo,read:org,read:user"}
    )
    assert granted == ["repo", "read:org", "read:user"]


def test_google_default_reads_space_delimited_scope() -> None:
    granted = _oauth_provider(ExternalAppType.GMAIL).extract_granted_scopes(
        {"access_token": "at", "scope": "openid https://mail.google.com/"}
    )
    assert granted == ["openid", "https://mail.google.com/"]


def test_default_missing_scope_is_none() -> None:
    provider = _oauth_provider(ExternalAppType.LINEAR)
    assert provider.extract_granted_scopes({"access_token": "at"}) is None


# --- Slack: scope is nested under `authed_user` ------------------------------


def test_slack_reads_nested_authed_user_scope() -> None:
    granted = _oauth_provider(ExternalAppType.SLACK).extract_granted_scopes(
        {
            "access_token": "bot-token",
            "authed_user": {"scope": "channels:read,chat:write"},
        }
    )
    assert granted == ["channels:read", "chat:write"]


def test_slack_missing_authed_user_is_none() -> None:
    provider = _oauth_provider(ExternalAppType.SLACK)
    assert provider.extract_granted_scopes({"access_token": "bot-token"}) is None


# --- HubSpot: out-of-band token-info lookup, strictly best-effort ------------


def _token_info_response(status_code: int, body: Any) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _patch_token_info(
    monkeypatch: pytest.MonkeyPatch, response_or_exc: object
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _get(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        if isinstance(response_or_exc, Exception):
            raise response_or_exc
        return response_or_exc

    monkeypatch.setattr(hubspot_module.requests, "get", _get)
    return captured


def test_hubspot_fetches_granted_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    scopes = ["crm.objects.contacts.read", "crm.objects.contacts.write"]
    captured = _patch_token_info(
        monkeypatch, _token_info_response(200, {"scopes": scopes})
    )

    granted = HubspotProvider().extract_granted_scopes({"access_token": "at-123"})

    assert granted == scopes
    assert captured["url"].endswith("/oauth/v1/access-tokens/at-123")


def test_hubspot_network_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_token_info(monkeypatch, requests.ConnectionError("connection reset"))
    assert HubspotProvider().extract_granted_scopes({"access_token": "at"}) is None


def test_hubspot_http_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_token_info(monkeypatch, _token_info_response(401, {"message": "expired"}))
    assert HubspotProvider().extract_granted_scopes({"access_token": "at"}) is None


def test_hubspot_missing_scopes_field_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_token_info(monkeypatch, _token_info_response(200, {"hub_id": 42}))
    assert HubspotProvider().extract_granted_scopes({"access_token": "at"}) is None


def test_hubspot_missing_access_token_skips_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: Any, **_k: Any) -> object:
        raise AssertionError("token-info must not be called without an access token")

    monkeypatch.setattr(hubspot_module.requests, "get", _boom)
    assert HubspotProvider().extract_granted_scopes({}) is None
