"""The HMR websocket upgrade must reject cross-site origins.

WebSockets are exempt from the same-origin policy and cookie auth is attached
automatically, so without this check any website could open the socket with a
victim's ambient credentials (cross-site WebSocket hijacking).
"""

from __future__ import annotations

import pytest

from onyx.server.features.build import webapp_proxy


@pytest.fixture(autouse=True)
def _web_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webapp_proxy, "WEB_DOMAIN", "https://cloud.onyx.app")


def test_same_origin_allowed() -> None:
    assert webapp_proxy._is_allowed_websocket_origin("https://cloud.onyx.app")


def test_host_is_case_insensitive() -> None:
    assert webapp_proxy._is_allowed_websocket_origin("https://Cloud.Onyx.App")


def test_cross_site_origin_rejected() -> None:
    assert not webapp_proxy._is_allowed_websocket_origin("https://evil.example")


def test_scheme_downgrade_rejected() -> None:
    assert not webapp_proxy._is_allowed_websocket_origin("http://cloud.onyx.app")


def test_subdomain_rejected() -> None:
    assert not webapp_proxy._is_allowed_websocket_origin("https://evil.cloud.onyx.app")


def test_missing_origin_allowed() -> None:
    # Non-browser clients send no Origin and carry no ambient credentials.
    assert webapp_proxy._is_allowed_websocket_origin(None)
