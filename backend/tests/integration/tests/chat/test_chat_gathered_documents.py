"""A chat that searches twice shows each found document once, with the same
documents and citations live, in the saved answer, and on reload."""

from typing import Any
from uuid import uuid4

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
    tool_call_reply,
)
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.conftest import DocumentBuilderType
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)


def _answer_documents(packets: list[dict[str, Any]]) -> list[str]:
    """The document IDs of the answer's `message_start` packet."""
    starts = [
        packet["obj"]
        for packet in packets
        if packet["obj"].get("type") == "message_start"
        and packet["obj"].get("final_documents") is not None
    ]
    assert starts, "The answer has no documents"
    return [document["document_id"] for document in starts[-1]["final_documents"]]


def test_two_searches_show_each_document_once_live_and_on_reload(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    document_builder: DocumentBuilderType,
    mock_llm: MockLLMScript,
) -> None:
    # Two documents that both searches find. The search index keeps documents
    # of earlier tests, so the documents and queries share a unique term.
    term = f"project{uuid4().hex[:12]}"
    contents = [f"{term} budget notes", f"{term} staffing notes"]
    seeded = document_builder(contents)
    seeded_ids = {document.id for document in seeded}
    DocumentManager.wait_until_searchable(contents, admin_user)

    # The model searches, searches again for the same documents, then answers
    # with citations.
    first = ToolCall(
        id="call_search_1", name="internal_search", arguments={"queries": [term]}
    )
    second = ToolCall(
        id="call_search_2",
        name="internal_search",
        arguments={"queries": [f"{term} notes"]},
    )
    mock_llm.conversation(
        "chat",
        tool_call_reply(first, tool_choice="auto"),
        tool_call_reply(
            second,
            tool_choice="auto",
            conditions=RequestConditions(has_results_for=[first.id]),
        ),
        Reply(
            text="The budget [1] and the staffing [2].",
            conditions=RequestConditions(has_results_for=[second.id]),
        ),
    )

    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    try:
        response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message=f"What do we know about {term}?",
            user_performing_action=admin_user,
        )
        assert response.error is None

        # Live: the answer shows every found document once.
        live = _answer_documents(response.packets)
        assert seeded_ids <= set(live)
        assert len(live) == len(set(live))
        assert [document.document_id for document in response.top_documents] == live
        live_citations = {
            packet["obj"]["citation_number"]: packet["obj"]["document_id"]
            for packet in response.packets
            if packet["obj"].get("type") == "citation_info"
        }
        assert set(live_citations) == {1, 2}
        assert set(live_citations.values()) <= set(live)

        # Reload: the saved answer replays the same documents and citations.
        loaded = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            headers=admin_user.headers,
        )
        loaded.raise_for_status()
        session = loaded.json()
        assistant = session["messages"][-1]
        assert assistant["message_id"] == response.assistant_message_id
        assert {
            int(number): document for number, document in assistant["citations"].items()
        } == live_citations
        assert {
            document["document_id"] for document in assistant["context_docs"]
        } == set(live)
        replayed = session["packets"][-1]
        assert _answer_documents(replayed) == live
    finally:
        ChatSessionManager.delete(chat_session, admin_user)
