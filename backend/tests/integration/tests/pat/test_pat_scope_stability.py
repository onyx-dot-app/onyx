"""PAT permissions remain bounded by the permissions present at creation."""

from collections.abc import Iterator

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def token_owner(admin_user: DATestUser, basic_user: DATestUser) -> Iterator[DATestUser]:
    original_token_ids = {pat.id for pat in PATManager.list(basic_user)}
    try:
        yield basic_user
    finally:
        response = client.patch(
            f"{API_SERVER_URL}/manage/admin/users/admin-access",
            json={"user_email": basic_user.email, "is_admin": False},
            headers=admin_user.headers,
            cookies=admin_user.cookies,
            timeout=60,
        )
        assert response.status_code == 200, response.text
        for pat in PATManager.list(basic_user):
            if pat.id not in original_token_ids:
                PATManager.revoke(pat.id, basic_user)


def test_full_pat_does_not_gain_permissions_after_owner_promotion(
    admin_user: DATestUser, token_owner: DATestUser
) -> None:
    original = PATManager.create("before-promotion", None, token_owner)
    assert original.token is not None
    original_headers = PATManager.get_auth_headers(original.token)
    before = client.get(
        f"{API_SERVER_URL}/manage/users/counts", headers=original_headers, timeout=60
    )
    assert before.status_code == 403, before.text

    promotion = client.patch(
        f"{API_SERVER_URL}/manage/admin/users/admin-access",
        json={"user_email": token_owner.email, "is_admin": True},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=60,
    )
    assert promotion.status_code == 200, promotion.text
    session_response = client.get(
        f"{API_SERVER_URL}/manage/users/counts",
        headers=token_owner.headers,
        cookies=token_owner.cookies,
        timeout=60,
    )
    assert session_response.status_code == 200, session_response.text

    fresh = PATManager.create("after-promotion", None, token_owner)
    assert fresh.token is not None
    fresh_response = client.get(
        f"{API_SERVER_URL}/manage/users/counts",
        headers=PATManager.get_auth_headers(fresh.token),
        timeout=60,
    )
    assert fresh_response.status_code == 200, fresh_response.text

    original_response = client.get(
        f"{API_SERVER_URL}/manage/users/counts", headers=original_headers, timeout=60
    )
    assert original_response.status_code == 403, original_response.text


def test_child_pat_cannot_gain_permissions_beyond_its_parent(
    admin_user: DATestUser, token_owner: DATestUser
) -> None:
    parent = PATManager.create("parent-before-promotion", None, token_owner)
    assert parent.token is not None
    parent_user = token_owner.model_copy(
        update={"headers": PATManager.get_auth_headers(parent.token), "cookies": {}}
    )
    promotion = client.patch(
        f"{API_SERVER_URL}/manage/admin/users/admin-access",
        json={"user_email": token_owner.email, "is_admin": True},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=60,
    )
    assert promotion.status_code == 200, promotion.text

    scoped_child = PATManager.create(
        "read-chat-child", None, parent_user, scopes=[Permission.READ_CHAT]
    )
    assert scoped_child.scopes == ["read:chat"]
    assert scoped_child.token is not None
    read_response = client.get(
        f"{API_SERVER_URL}/chat/get-user-chat-sessions",
        headers=PATManager.get_auth_headers(scoped_child.token),
        timeout=60,
    )
    assert read_response.status_code == 200, read_response.text

    full_child = PATManager.create("full-child", None, parent_user)
    assert full_child.token is not None
    response = client.get(
        f"{API_SERVER_URL}/manage/users/counts",
        headers=PATManager.get_auth_headers(full_child.token),
        timeout=60,
    )
    assert response.status_code == 403, response.text


def test_explicit_child_cannot_escape_selected_parent_scope(
    token_owner: DATestUser,
) -> None:
    token = PATManager.create_scoped(
        "issuer-only", None, token_owner, [Permission.CREATE_USER_API_KEYS]
    )
    parent_user = token_owner.model_copy(
        update={"headers": PATManager.get_auth_headers(token), "cookies": {}}
    )
    response = PATManager.create_response(
        "broader-child", None, parent_user, scopes=[Permission.READ_CHAT]
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"
    full_child = PATManager.create_response("full-child-escape", None, parent_user)
    assert full_child.status_code == 403


@pytest.mark.parametrize(
    ("scope", "write_status"),
    [(Permission.READ_CHAT, 403), (Permission.WRITE_CHAT, 404)],
)
def test_explicit_chat_scopes_keep_their_access_and_round_trip(
    token_owner: DATestUser, scope: Permission, write_status: int
) -> None:
    pat = PATManager.create("chat-scope", None, token_owner, scopes=[scope])
    assert pat.scopes == [scope.value]
    listed = next(token for token in PATManager.list(token_owner) if token.id == pat.id)
    assert listed.scopes == [scope.value]
    assert pat.token is not None
    headers = PATManager.get_auth_headers(pat.token)

    read_response = client.get(
        f"{API_SERVER_URL}/chat/get-user-chat-sessions", headers=headers, timeout=60
    )
    assert read_response.status_code == 200, read_response.text
    write_response = client.post(
        f"{API_SERVER_URL}/chat/stop-chat-session/00000000-0000-0000-0000-000000000000",
        headers=headers,
        timeout=60,
    )
    assert write_response.status_code == write_status, write_response.text
