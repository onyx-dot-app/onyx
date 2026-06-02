"""Integration tests for PAT scope enforcement.

A PAT's scopes cap the request on top of the owner's permissions. Using the
real auth plumbing (PAT header -> request.state.token_scopes -> require_permission):

  - an unrestricted PAT (the default — no scopes) reaches BASIC_ACCESS
    endpoints, and
  - a PAT scoped to read:search is denied those same endpoints, because
    read:search does not cover BASIC_ACCESS.

This exercises the token-scope gate end-to-end against existing BASIC_ACCESS
routes (no fine-grained route guards required).
"""

from uuid import UUID

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.pat import create_pat
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

# A representative BASIC_ACCESS-guarded endpoint.
BASIC_ACCESS_ENDPOINT = ("GET", "/user/pats")


def _pat_headers(user: DATestUser, scopes: list[Permission] | None) -> dict[str, str]:
    with get_session_with_current_tenant() as db_session:
        _, raw_token = create_pat(
            db_session=db_session,
            user_id=UUID(user.id),
            name="scope_test_pat",
            expiration_days=None,
            scopes=scopes,
        )
        db_session.commit()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.fixture(scope="module")
def basic_user_unrestricted_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return _pat_headers(permission_basic_user, scopes=None)


@pytest.fixture(scope="module")
def basic_user_search_scoped_pat_headers(
    permission_basic_user: DATestUser,
) -> dict[str, str]:
    return _pat_headers(permission_basic_user, scopes=[Permission.READ_SEARCH])


def test_unrestricted_pat_reaches_basic_access_endpoint(
    basic_user_unrestricted_pat_headers: dict[str, str],
) -> None:
    method, path = BASIC_ACCESS_ENDPOINT
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=basic_user_unrestricted_pat_headers,
        timeout=30,
    )
    assert resp.status_code < 400, (
        f"Unrestricted PAT should reach {method} {path}, got {resp.status_code}"
    )


def test_search_scoped_pat_denied_on_basic_access_endpoint(
    basic_user_search_scoped_pat_headers: dict[str, str],
) -> None:
    method, path = BASIC_ACCESS_ENDPOINT
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=basic_user_search_scoped_pat_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"read:search-scoped PAT should be denied on {method} {path} "
        f"(read:search does not cover basic), got {resp.status_code}"
    )


# /me uses optional_user with no require_permission — an "unguarded" route. The
# fail-closed gate denies a scoped PAT there while leaving an unrestricted PAT
# (and sessions / API keys) untouched.
UNGUARDED_ENDPOINT = ("GET", "/me")


def test_unrestricted_pat_reaches_unguarded_endpoint(
    basic_user_unrestricted_pat_headers: dict[str, str],
) -> None:
    method, path = UNGUARDED_ENDPOINT
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=basic_user_unrestricted_pat_headers,
        timeout=30,
    )
    assert resp.status_code < 400, (
        f"Unrestricted PAT should reach {method} {path}, got {resp.status_code}"
    )


def test_scoped_pat_denied_on_unguarded_endpoint(
    basic_user_search_scoped_pat_headers: dict[str, str],
) -> None:
    method, path = UNGUARDED_ENDPOINT
    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=basic_user_search_scoped_pat_headers,
        timeout=30,
    )
    assert resp.status_code == 403, (
        f"A scoped PAT must be denied on the unguarded route {method} {path} "
        f"(fail-closed), got {resp.status_code}"
    )
