"""Integration test for the mobile SSO code-exchange endpoint (PR 4).

Exercises the real `/auth/mobile/sso/exchange` endpoint end-to-end: a real
session token is stashed behind a one-time PKCE-bound code (as
`complete_mobile_sso` would do), the app swaps the code for the token, the token
authenticates `/me`, and replay / wrong-verifier attempts fail with a generic
401. The Google leg itself can't be driven without a live IdP, so we stash a
genuine bearer token (minted via `/auth/mobile/login`) and verify the bridge.
"""

import asyncio

import httpx

from onyx.auth.mobile_sso.code_store import store_sso_code
from onyx.auth.users import generate_pkce_pair
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.mobile_auth._helpers import bearer
from tests.integration.tests.mobile_auth._helpers import mobile_login


def _exchange(code: str, code_verifier: str) -> httpx.Response:
    return client.post(
        url=f"{API_SERVER_URL}/auth/mobile/sso/exchange",
        json={"code": code, "code_verifier": code_verifier},
        headers=GENERAL_HEADERS,
    )


def test_mobile_sso_exchange_round_trip(admin_user: DATestUser) -> None:
    # A real, revocable session token (as a provider callback would mint).
    login_resp = mobile_login(admin_user.email, admin_user.password)
    login_resp.raise_for_status()
    token = login_resp.json()["access_token"]
    assert token
    client.cookies.clear()

    # Stash it behind a one-time PKCE-bound code, exactly like complete_mobile_sso.
    verifier, challenge = generate_pkce_pair()
    code = asyncio.run(store_sso_code(token, challenge))

    resp = _exchange(code, verifier)
    resp.raise_for_status()
    body = resp.json()
    assert body["token_type"].lower() == "bearer"
    assert body["access_token"] == token

    me = client.get(url=f"{API_SERVER_URL}/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == admin_user.email
    client.cookies.clear()

    # Single-use: replaying the same code now fails with a generic 401.
    replay = _exchange(code, verifier)
    assert replay.status_code == 401
