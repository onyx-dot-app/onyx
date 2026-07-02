"""Integration tests for READ_CHAT / WRITE_CHAT scope enforcement on chat routes."""

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.http_client import request_status
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser

_SESSION_ID = "00000000-0000-0000-0000-000000000000"

READ_CHAT_ROUTE = ("GET", "/chat/get-user-chat-sessions")
WRITE_CHAT_ROUTE = ("POST", f"/chat/stop-chat-session/{_SESSION_ID}")
BASIC_ONLY_ROUTE = ("DELETE", f"/chat/delete-chat-session/{_SESSION_ID}")
# read:chat route on the allow_anonymous path.
CHAT_DEP_ROUTE = ("GET", f"/chat/get-chat-session/{_SESSION_ID}")


@pytest.fixture(scope="module")
def read_chat_headers(permission_basic_user: DATestUser) -> dict[str, str]:
    return PATManager.scoped_auth_headers(
        "chat_scope_test_pat", None, permission_basic_user, [Permission.READ_CHAT]
    )


@pytest.fixture(scope="module")
def write_chat_headers(permission_basic_user: DATestUser) -> dict[str, str]:
    return PATManager.scoped_auth_headers(
        "chat_scope_test_pat", None, permission_basic_user, [Permission.WRITE_CHAT]
    )


@pytest.fixture(scope="module")
def read_search_headers(permission_basic_user: DATestUser) -> dict[str, str]:
    return PATManager.scoped_auth_headers(
        "chat_scope_test_pat", None, permission_basic_user, [Permission.READ_SEARCH]
    )


def test_read_chat_reaches_read_route(read_chat_headers: dict[str, str]) -> None:
    assert request_status(read_chat_headers, READ_CHAT_ROUTE) < 400


def test_read_chat_denied_on_write_route(read_chat_headers: dict[str, str]) -> None:
    assert request_status(read_chat_headers, WRITE_CHAT_ROUTE) == 403


def test_read_chat_denied_on_basic_route(read_chat_headers: dict[str, str]) -> None:
    assert request_status(read_chat_headers, BASIC_ONLY_ROUTE) == 403


def test_write_chat_reaches_read_route(write_chat_headers: dict[str, str]) -> None:
    assert request_status(write_chat_headers, READ_CHAT_ROUTE) < 400


def test_write_chat_reaches_write_route(write_chat_headers: dict[str, str]) -> None:
    # bogus id -> 4xx, never 403
    assert request_status(write_chat_headers, WRITE_CHAT_ROUTE) != 403


def test_write_chat_denied_on_delete(write_chat_headers: dict[str, str]) -> None:
    assert request_status(write_chat_headers, BASIC_ONLY_ROUTE) == 403


def test_read_chat_reaches_chat_dep_route(read_chat_headers: dict[str, str]) -> None:
    # bogus id -> 4xx, never 403
    assert request_status(read_chat_headers, CHAT_DEP_ROUTE) != 403


def test_non_chat_scope_denied_on_chat_dep_route(
    read_search_headers: dict[str, str],
) -> None:
    assert request_status(read_search_headers, CHAT_DEP_ROUTE) == 403


def test_limited_service_account_reaches_chat(
    limited_service_account: DATestAPIKey,
) -> None:
    """LIMITED service-account keys (e.g. the Discord bot) hold write:chat
    (implies read:chat), so they reach the chat surface but not basic-only routes."""
    headers = limited_service_account.headers
    assert request_status(headers, READ_CHAT_ROUTE) < 400
    # bogus id -> 4xx, never 403
    assert request_status(headers, WRITE_CHAT_ROUTE) != 403
    assert request_status(headers, BASIC_ONLY_ROUTE) == 403
