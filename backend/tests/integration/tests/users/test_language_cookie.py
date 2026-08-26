"""Integration tests for backend-owned locale cookie reconciliation.

The backend owns the NEXT_LOCALE cookie the web server layout reads:
- PATCH /user/language sets it alongside the DB update
- GET /me sets it when the request cookie disagrees with the stored preference
"""

import httpx

from onyx.configs.constants import NEXT_LOCALE_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _locale_cookie(response: httpx.Response) -> str | None:
    return response.cookies.get(NEXT_LOCALE_COOKIE_NAME)


def _headers_with_locale_cookie(user: DATestUser, locale: str) -> dict[str, str]:
    # user.headers carries the auth cookie in an explicit Cookie header, and
    # the client's cookie jar is skipped when a request already has one — the
    # locale cookie must be appended to the header itself.
    return {
        **user.headers,
        "Cookie": f"{user.headers['Cookie']}; {NEXT_LOCALE_COOKIE_NAME}={locale}",
    }


def test_language_patch_sets_locale_cookie(reset: None) -> None:  # noqa: ARG001
    user: DATestUser = UserManager.create()

    response = client.patch(
        url=f"{API_SERVER_URL}/user/language",
        json={"language": "es"},
        headers=user.headers,
    )
    response.raise_for_status()
    assert _locale_cookie(response) == "es"

    # The stored preference now reads back as Spanish.
    me = client.get(url=f"{API_SERVER_URL}/me", headers=user.headers)
    me.raise_for_status()
    assert me.json()["preferences"]["language"] == "es"


def test_me_reconciles_stale_locale_cookie(reset: None) -> None:  # noqa: ARG001
    user: DATestUser = UserManager.create()

    client.patch(
        url=f"{API_SERVER_URL}/user/language",
        json={"language": "de"},
        headers=user.headers,
    ).raise_for_status()

    # A request without a locale cookie gets one set from the preference.
    missing = client.get(url=f"{API_SERVER_URL}/me", headers=user.headers)
    missing.raise_for_status()
    assert _locale_cookie(missing) == "de"

    # A request carrying a stale locale cookie gets it reconciled.
    stale = client.get(
        url=f"{API_SERVER_URL}/me",
        headers=_headers_with_locale_cookie(user, "fr"),
    )
    stale.raise_for_status()
    assert _locale_cookie(stale) == "de"

    # A request already carrying the right cookie is left alone.
    current = client.get(
        url=f"{API_SERVER_URL}/me",
        headers=_headers_with_locale_cookie(user, "de"),
    )
    current.raise_for_status()
    assert _locale_cookie(current) is None
