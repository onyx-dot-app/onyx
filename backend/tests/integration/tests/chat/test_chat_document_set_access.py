"""Integration tests for document set access enforcement in search filters.

Covers the bypass where a user could override a persona's configured document
sets by supplying `internal_search_filters.document_set` on a chat message.

The SearchTool is only invoked when the LLM decides to call it, so these tests
force the call with `forced_tool_id` + `mock_llm_response` to make coverage
deterministic. They also need a seeded connector because DocumentSetManager
rejects creation with no connectors.
"""

import json
import os
from uuid import UUID

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Document set group restrictions are enterprise only",
)

_MOCK_SEARCH_TOOL_CALL = (
    '{"name":"internal_search","arguments":{"queries":["test query"]}}'
)


def _get_internal_search_tool_id(admin_user: DATestUser) -> int:
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    for tool in tools:
        if tool.in_code_tool_id == SEARCH_TOOL_ID:
            return tool.id
    raise AssertionError("SearchTool must exist for this test")


def _setup_search_infrastructure() -> tuple[DATestUser, DATestUser, int, int]:
    """Admin + basic user, a seeded connector, an LLM provider, and the
    SearchTool id. Required because DocumentSetManager rejects empty connector
    fields and SearchTool is only exposed when at least one connector exists."""
    admin_user = UserManager.create(name="admin_user")
    basic_user = UserManager.create(name="basic_user")
    LLMProviderManager.create(user_performing_action=admin_user)
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    search_tool_id = _get_internal_search_tool_id(admin_user)
    return admin_user, basic_user, cc_pair.id, search_tool_id


def _send_message_with_document_set_filter(
    user: DATestUser,
    chat_session_id: UUID,
    document_set_names: list[str],
    forced_tool_id: int,
) -> requests.Response:
    return requests.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json={
            "message": "hello",
            "chat_session_id": str(chat_session_id),
            "stream": True,
            "internal_search_filters": {"document_set": document_set_names},
            "forced_tool_id": forced_tool_id,
            "mock_llm_response": _MOCK_SEARCH_TOOL_CALL,
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


def _create_search_persona_chat_session(
    admin_user: DATestUser,
    basic_user: DATestUser,
    search_tool_id: int,
) -> UUID:
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="search_persona",
        tool_ids=[search_tool_id],
    )
    chat_session = ChatSessionManager.create(
        user_performing_action=basic_user,
        persona_id=persona.id,
    )
    return chat_session.id


def test_document_set_filter_blocks_unauthorized_names(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user, basic_user, cc_pair_id, search_tool_id = _setup_search_infrastructure()

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
        cc_pair_ids=[cc_pair_id],
    )

    chat_session_id = _create_search_persona_chat_session(
        admin_user, basic_user, search_tool_id
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session_id,
        document_set_names=[restricted_doc_set.name],
        forced_tool_id=search_tool_id,
    )

    assert _stream_contains_error(response, "document set"), (
        "Expected an access-denied error in the stream when filtering with an "
        "unauthorized document set name."
    )


def test_document_set_filter_allows_authorized_names(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user, basic_user, cc_pair_id, search_tool_id = _setup_search_infrastructure()

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
        cc_pair_ids=[cc_pair_id],
    )

    chat_session_id = _create_search_persona_chat_session(
        admin_user, basic_user, search_tool_id
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session_id,
        document_set_names=[allowed_doc_set.name],
        forced_tool_id=search_tool_id,
    )

    assert not _stream_contains_error(
        response, "document set"
    ), "Did not expect an access-denied error for an authorized document set."


def test_public_document_set_is_accessible_to_any_user(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user, basic_user, cc_pair_id, search_tool_id = _setup_search_infrastructure()

    public_doc_set = DocumentSetManager.create(
        user_performing_action=admin_user,
        name="public_doc_set",
        is_public=True,
        cc_pair_ids=[cc_pair_id],
    )

    chat_session_id = _create_search_persona_chat_session(
        admin_user, basic_user, search_tool_id
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session_id,
        document_set_names=[public_doc_set.name],
        forced_tool_id=search_tool_id,
    )

    assert not _stream_contains_error(response, "document set")


def test_nonexistent_document_set_name_is_blocked(
    reset: None,  # noqa: ARG001
) -> None:
    """Names that don't correspond to any existing document set are treated as
    inaccessible — callers shouldn't be able to probe for existence by getting
    silent acceptance."""
    admin_user, basic_user, _, search_tool_id = _setup_search_infrastructure()

    chat_session_id = _create_search_persona_chat_session(
        admin_user, basic_user, search_tool_id
    )

    response = _send_message_with_document_set_filter(
        user=basic_user,
        chat_session_id=chat_session_id,
        document_set_names=["this_document_set_does_not_exist"],
        forced_tool_id=search_tool_id,
    )

    assert _stream_contains_error(response, "document set")
