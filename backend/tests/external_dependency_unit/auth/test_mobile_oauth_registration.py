"""Regression guard: the mobile Google OAuth surface must register under google_oauth.

Two bugs reached a running google_oauth deployment because the rest of the suite
only ever boots the app under basic auth:
  1. /auth/mobile/oauth/{authorize,callback} were missing from PUBLIC_ENDPOINT_SPECS,
     so check_router_auth raised at startup and crash-looped the api_server.
  2. The mobile gateway (which owns /auth/mobile/sso/exchange) was mounted only for
     AUTH_TYPE basic/cloud, so the SSO exchange 404'd on a google_oauth instance.

get_application() reads AUTH_TYPE as a module global at call time, so monkeypatching
it boots the google_oauth surface in-process. Building it also runs check_router_auth,
so bug #1 raises here while the assertions cover bug #2.
"""

import pytest

import onyx.main as onyx_main
from onyx.configs.constants import AuthType


def test_mobile_routes_registered_under_google_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onyx_main, "AUTH_TYPE", AuthType.GOOGLE_OAUTH)
    monkeypatch.setattr(onyx_main, "OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(onyx_main, "OAUTH_CLIENT_SECRET", "test-client-secret")

    paths = {getattr(route, "path", "") for route in onyx_main.get_application().routes}

    # Dedicated OAuth router (callback routes to the api_server, not the web app)
    # plus the gateway's exchange that swaps the one-time code for the token.
    assert {
        "/auth/mobile/oauth/authorize",
        "/auth/mobile/oauth/callback",
        "/auth/mobile/sso/exchange",
    } <= paths
