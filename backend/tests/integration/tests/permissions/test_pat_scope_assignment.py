"""Integration tests for assigning scopes when minting a PAT via the user API.

Minting needs CREATE_USER_API_KEYS, so those tests use ``pat_creator``. Listing
scopes is BASIC_ACCESS and stays on the basic user, proving it needs no creation
rights.
"""

from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module")
def pat_creator(permission_holder_user_factory: Any) -> DATestUser:
    return permission_holder_user_factory(Permission.CREATE_USER_API_KEYS.value)


# The scopes a user may assign today (admin scopes are intentionally excluded).
EXPECTED_SELECTABLE_SCOPES = {
    Permission.READ_SEARCH.value,
    Permission.READ_CHAT.value,
    Permission.WRITE_CHAT.value,
    Permission.USE_LLM_GATEWAY.value,
}


def test_selectable_scopes_endpoint(permission_basic_user: DATestUser) -> None:
    options = PATManager.selectable_scopes(permission_basic_user)
    assert {option["scope"] for option in options} == EXPECTED_SELECTABLE_SCOPES
    assert all(option["label"] and option["description"] for option in options)


def test_scope_implications(permission_basic_user: DATestUser) -> None:
    by_scope = {
        o["scope"]: o for o in PATManager.selectable_scopes(permission_basic_user)
    }
    # write:chat implies read:chat (write superset of read); reads imply nothing.
    assert by_scope[Permission.WRITE_CHAT.value]["implies"] == [
        Permission.READ_CHAT.value
    ]
    assert by_scope[Permission.READ_CHAT.value]["implies"] == []
    assert by_scope[Permission.READ_SEARCH.value]["implies"] == []
    assert by_scope[Permission.USE_LLM_GATEWAY.value]["implies"] == []
    assert by_scope[Permission.USE_LLM_GATEWAY.value]["min_tier"] == "business"


def test_scopes_round_trip(pat_creator: DATestUser) -> None:
    scopes = [Permission.READ_SEARCH, Permission.READ_CHAT]
    expected = {s.value for s in scopes}
    created = PATManager.create("scoped-token", None, pat_creator, scopes=scopes)
    assert created.scopes is not None and set(created.scopes) == expected

    listed = next(pat for pat in PATManager.list(pat_creator) if pat.id == created.id)
    assert listed.scopes is not None and set(listed.scopes) == expected


def test_unscoped_token_is_unrestricted(pat_creator: DATestUser) -> None:
    created = PATManager.create("full-token", None, pat_creator)
    assert created.scopes is None


def test_empty_scopes_rejected(pat_creator: DATestUser) -> None:
    response = PATManager.create_response("empty-token", None, pat_creator, scopes=[])
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_non_selectable_scope_rejected(pat_creator: DATestUser) -> None:
    response = PATManager.create_response(
        "admin-token", None, pat_creator, scopes=[Permission.READ_ADMIN]
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"
