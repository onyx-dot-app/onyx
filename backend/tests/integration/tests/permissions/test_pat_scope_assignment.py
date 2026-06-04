"""Integration tests for assigning scopes when minting a PAT via the user API."""

from onyx.db.enums import Permission
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser

# The scopes a user may assign today (admin scopes are intentionally excluded).
EXPECTED_SELECTABLE_SCOPES = {
    Permission.READ_SEARCH.value,
    Permission.READ_CHAT.value,
    Permission.WRITE_CHAT.value,
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


def test_scopes_round_trip(permission_basic_user: DATestUser) -> None:
    scopes = [Permission.READ_SEARCH, Permission.READ_CHAT]
    expected = {s.value for s in scopes}
    created = PATManager.create(
        "scoped-token", None, permission_basic_user, scopes=scopes
    )
    assert created.scopes is not None and set(created.scopes) == expected

    listed = next(
        pat for pat in PATManager.list(permission_basic_user) if pat.id == created.id
    )
    assert listed.scopes is not None and set(listed.scopes) == expected


def test_unscoped_token_is_unrestricted(permission_basic_user: DATestUser) -> None:
    created = PATManager.create("full-token", None, permission_basic_user)
    assert created.scopes is None


def test_empty_scopes_rejected(permission_basic_user: DATestUser) -> None:
    response = PATManager.create_response(
        "empty-token", None, permission_basic_user, scopes=[]
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_non_selectable_scope_rejected(permission_basic_user: DATestUser) -> None:
    response = PATManager.create_response(
        "admin-token", None, permission_basic_user, scopes=[Permission.READ_ADMIN]
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_INPUT"
