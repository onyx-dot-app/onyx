"""Integration tests for document set access enforcement in search filters.

Covers the bypass where a user could override a persona's configured document
sets by supplying `internal_search_filters.document_set` on a chat message.
"""

import json
import os
from uuid import UUID

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Document set group restrictions are enterprise only",
)


def _send_message_with_document_set_filter(
    user: DATestUser,
    chat_session_id: UUID,
    document_set_names: list[str],
) -> requests.Response:
    return requests.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json={
            "message": "hello",
            "chat_session_id": str(chat_session_id),
            "stream": True,
            "internal_search_filters": {"document_set": document_set_names},
        },
        headers=user.headers,
        stream=True,
        cookies=user.cookies,
    )


def _stream_contains_error(response: requests.Response, needle: str) -> bool:
    needle_lower = needle.lower()
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        err = payload.get("error")
        if isinstance(err, str) and needle_lower in err.lower():
            return True
    return False


def test_document_set_filter_blocks_unauthorized_names(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")

    restricted_group = UserGroupManager.create(
        user_performing_action=admin_user,
        name="restricted_doc_set_group",
        user_ids=[],  # basic_user is NOT in this group
    )
    restricted_doc_set = DocumentSetManager.create(
        user_performing_action=admin_user,
        name="restricted_doc_set",
        is_public=False,
        groups=[restricted_group.id],
    )

    chat_session = ChatSessionManager.create(
        user_performing_action=basic_user,
        persona_id=0,
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session.id,
        document_set_names=[restricted_doc_set.name],
    )

    assert _stream_contains_error(response, "document set"), (
        "Expected an access-denied error in the stream when filtering with an "
        "unauthorized document set name."
    )


def test_document_set_filter_allows_authorized_names(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")

    allowed_group = UserGroupManager.create(
        user_performing_action=admin_user,
        name="allowed_doc_set_group",
        user_ids=[basic_user.id],
    )
    allowed_doc_set = DocumentSetManager.create(
        user_performing_action=admin_user,
        name="allowed_doc_set",
        is_public=False,
        groups=[allowed_group.id],
    )

    chat_session = ChatSessionManager.create(
        user_performing_action=basic_user,
        persona_id=0,
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session.id,
        document_set_names=[allowed_doc_set.name],
    )

    # No access-denied error should surface for an authorized document set.
    assert not _stream_contains_error(
        response, "document set"
    ), "Did not expect an access-denied error for an authorized document set."


def test_public_document_set_is_accessible_to_any_user(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")

    public_doc_set = DocumentSetManager.create(
        user_performing_action=admin_user,
        name="public_doc_set",
        is_public=True,
    )

    chat_session = ChatSessionManager.create(
        user_performing_action=basic_user,
        persona_id=0,
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session.id,
        document_set_names=[public_doc_set.name],
    )

    assert not _stream_contains_error(response, "document set")


def test_nonexistent_document_set_name_is_blocked(
    reset: None,  # noqa: ARG001
) -> None:
    """Names that don't correspond to any existing document set are treated as
    inaccessible — callers shouldn't be able to probe for existence by getting
    silent acceptance."""
    UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")

    chat_session = ChatSessionManager.create(
        user_performing_action=basic_user,
        persona_id=0,
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session.id,
        document_set_names=["this_document_set_does_not_exist"],
    )

    assert _stream_contains_error(response, "document set")
