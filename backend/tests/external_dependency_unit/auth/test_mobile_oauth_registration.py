"""Regression guard: the mobile Google OAuth surface must register whenever env
Google OAuth credentials are configured.

get_application() reads OAUTH_ENABLED and the client credentials as module
globals at call time, so monkeypatching boots the OAuth-enabled surface
in-process. Building the app also runs check_router_auth, which raises if the
mobile routes are missing from PUBLIC_ENDPOINT_SPECS. The assertions cover the
gateway's SSO exchange and the dedicated mobile OAuth router.
"""

import pytest

import onyx.main as onyx_main


def test_mobile_routes_registered_with_env_google_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onyx_main, "OAUTH_ENABLED", True)
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
