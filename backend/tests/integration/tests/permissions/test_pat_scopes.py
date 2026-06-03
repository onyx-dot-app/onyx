"""Integration tests for PAT scope enforcement through the real auth plumbing."""

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser

BASIC_ACCESS_ENDPOINT = ("GET", "/user/pats")
IDENTITY_ENDPOINT = ("GET", "/me")


def _pat_headers(user: DATestUser, scopes: list[Permission] | None) -> dict[str, str]:
    raw_token = PATManager.create_scoped(
        name="scope_test_pat",
        expiration_days=None,
        user_performing_action=user,
        scopes=scopes,
    )
    return PATManager.get_auth_headers(raw_token)


@pytest.fixture(scope="module")
def unrestricted_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return _pat_headers(permission_basic_user, scopes=None)


@pytest.fixture(scope="module")
def search_scoped_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return _pat_headers(permission_basic_user, scopes=[Permission.READ_SEARCH])


def _request(headers: dict[str, str], endpoint: tuple[str, str]) -> int:
    method, path = endpoint
    return client.request(
        method, f"{API_SERVER_URL}{path}", headers=headers, timeout=30
    ).status_code


def test_unrestricted_pat_reaches_basic_access_endpoint(
    unrestricted_pat_headers: dict[str, str],
) -> None:
    status = _request(unrestricted_pat_headers, BASIC_ACCESS_ENDPOINT)
    assert status < 400, (
        f"Unrestricted PAT should reach BASIC_ACCESS route, got {status}"
    )


def test_search_scoped_pat_denied_on_basic_access_endpoint(
    search_scoped_pat_headers: dict[str, str],
) -> None:
    status = _request(search_scoped_pat_headers, BASIC_ACCESS_ENDPOINT)
    assert status == 403, (
        f"read:search PAT should be denied on BASIC_ACCESS route, got {status}"
    )


def test_search_scoped_pat_reaches_identity_endpoint(
    search_scoped_pat_headers: dict[str, str],
) -> None:
    status = _request(search_scoped_pat_headers, IDENTITY_ENDPOINT)
    assert status < 400, f"scoped PAT should reach the scope-exempt /me, got {status}"


def test_unrestricted_pat_reaches_identity_endpoint(
    unrestricted_pat_headers: dict[str, str],
) -> None:
    status = _request(unrestricted_pat_headers, IDENTITY_ENDPOINT)
    assert status < 400, f"Unrestricted PAT should reach /me, got {status}"
