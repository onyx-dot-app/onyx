"""Integration tests for PAT scope enforcement through the real auth plumbing."""

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.http_client import request_status
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser

BASIC_ACCESS_ENDPOINT = ("GET", "/user/pats")
IDENTITY_ENDPOINT = ("GET", "/me")


@pytest.fixture(scope="module")
def unrestricted_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return PATManager.scoped_auth_headers(
        "scope_test_pat", None, permission_basic_user, None
    )


@pytest.fixture(scope="module")
def search_scoped_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return PATManager.scoped_auth_headers(
        "scope_test_pat", None, permission_basic_user, [Permission.READ_SEARCH]
    )


def test_unrestricted_pat_reaches_basic_access_endpoint(
    unrestricted_pat_headers: dict[str, str],
) -> None:
    status = request_status(unrestricted_pat_headers, BASIC_ACCESS_ENDPOINT)
    assert status < 400, (
        f"Unrestricted PAT should reach BASIC_ACCESS route, got {status}"
    )


def test_search_scoped_pat_denied_on_basic_access_endpoint(
    search_scoped_pat_headers: dict[str, str],
) -> None:
    status = request_status(search_scoped_pat_headers, BASIC_ACCESS_ENDPOINT)
    assert status == 403, (
        f"read:search PAT should be denied on BASIC_ACCESS route, got {status}"
    )


def test_search_scoped_pat_reaches_identity_endpoint(
    search_scoped_pat_headers: dict[str, str],
) -> None:
    status = request_status(search_scoped_pat_headers, IDENTITY_ENDPOINT)
    assert status < 400, f"scoped PAT should reach the scope-exempt /me, got {status}"


def test_unrestricted_pat_reaches_identity_endpoint(
    unrestricted_pat_headers: dict[str, str],
) -> None:
    status = request_status(unrestricted_pat_headers, IDENTITY_ENDPOINT)
    assert status < 400, f"Unrestricted PAT should reach /me, got {status}"
