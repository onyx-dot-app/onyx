from uuid import uuid4

import pytest
import requests
from requests import HTTPError

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.user import build_email
from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    """Reset all data once before running any tests in this module."""
    reset_all()


@pytest.fixture
def second_user(admin_user: DATestUser) -> DATestUser:  # noqa: ARG001
    # Ensure admin exists so this new user is created with BASIC role.
    try:
        return UserManager.create(name="second_basic_user")
    except HTTPError as e:
        response = e.response
        if response is None:
            raise
        if response.status_code not in (400, 409):
            raise
        try:
            payload = response.json()
        except ValueError:
            raise
        detail = payload.get("detail")
        if not _is_user_already_exists_detail(detail):
            raise
        print("Second basic user already exists; logging in instead.")
        return UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email("second_basic_user"),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.BASIC,
                is_active=True,
            )
        )


def _is_user_already_exists_detail(detail: object) -> bool:
    if isinstance(detail, str):
        normalized = detail.lower()
        return (
            "already exists" in normalized
            or "register_user_already_exists" in normalized
        )
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code.lower() == "register_user_already_exists":
            return True
        message = detail.get("message")
        if isinstance(message, str) and "already exists" in message.lower():
            return True
    return False


def _get_chat_session(
    chat_session_id: str,
    user: DATestUser,
    is_shared: bool | None = None,
    include_deleted: bool | None = None,
) -> requests.Response:
    params: dict[str, str] = {}
    if is_shared is not None:
        params["is_shared"] = str(is_shared).lower()
    if include_deleted is not None:
        params["include_deleted"] = str(include_deleted).lower()

    return requests.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        params=params,
        headers=user.headers,
        cookies=user.cookies,
    )


def _set_sharing_status(
    chat_session_id: str, sharing_status: str, user: DATestUser
) -> requests.Response:
    return requests.patch(
        f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}",
        json={"sharing_status": sharing_status},
        headers=user.headers,
        cookies=user.cookies,
    )


def test_private_chat_session_access(
    basic_user: DATestUser, second_user: DATestUser
) -> None:
    """Verify private sessions are only accessible by the owner and never via share link."""
    # Create a private chat session owned by basic_user.
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    # Owner can access the private session normally.
    response = _get_chat_session(str(chat_session.id), basic_user)
    assert response.status_code == 200

    # Share link should be forbidden when the session is private.
    response = _get_chat_session(str(chat_session.id), basic_user, is_shared=True)
    assert response.status_code == 403

    # Other users cannot access private sessions directly.
    response = _get_chat_session(str(chat_session.id), second_user)
    assert response.status_code == 403

    # Other users also cannot access private sessions via share link.
    response = _get_chat_session(str(chat_session.id), second_user, is_shared=True)
    assert response.status_code == 403


def test_public_shared_chat_session_access(
    basic_user: DATestUser, second_user: DATestUser
) -> None:
    """Verify shared sessions are accessible only via share link for non-owners."""
    # Create a private session, then mark it public.
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    response = _set_sharing_status(str(chat_session.id), "public", basic_user)
    assert response.status_code == 200

    # Owner can access normally.
    response = _get_chat_session(str(chat_session.id), basic_user)
    assert response.status_code == 200

    # Owner can also access via share link.
    response = _get_chat_session(str(chat_session.id), basic_user, is_shared=True)
    assert response.status_code == 200

    # Non-owner cannot access without share link.
    response = _get_chat_session(str(chat_session.id), second_user)
    assert response.status_code == 403

    # Non-owner can access with share link for public sessions.
    response = _get_chat_session(str(chat_session.id), second_user, is_shared=True)
    assert response.status_code == 200


def test_deleted_chat_session_access(
    basic_user: DATestUser, second_user: DATestUser
) -> None:
    """Verify deleted sessions return 404, with include_deleted gated by access checks."""
    # Create and soft-delete a session.
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    deletion_success = ChatSessionManager.soft_delete(
        chat_session=chat_session, user_performing_action=basic_user
    )
    assert deletion_success is True

    # Deleted sessions are not accessible normally.
    response = _get_chat_session(str(chat_session.id), basic_user)
    assert response.status_code == 404

    # Owner can fetch deleted session only with include_deleted.
    response = _get_chat_session(str(chat_session.id), basic_user, include_deleted=True)
    assert response.status_code == 200
    assert response.json().get("deleted") is True

    # Non-owner should be blocked even with include_deleted.
    response = _get_chat_session(
        str(chat_session.id), second_user, include_deleted=True
    )
    assert response.status_code == 403


def test_chat_session_not_found_returns_404(basic_user: DATestUser) -> None:
    """Verify unknown IDs return 404."""
    response = _get_chat_session(str(uuid4()), basic_user)
    assert response.status_code == 404
