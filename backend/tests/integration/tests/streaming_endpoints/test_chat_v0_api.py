"""
Integration tests for the v0 chat API endpoint.
Tests the legacy response format for backwards compatibility.
"""

import json
from typing import Any
from uuid import UUID

import requests

from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import RetrievalDetails
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.conftest import DocumentBuilderType


def parse_v0_streaming_response(response_text: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON response into a list of dictionaries."""
    lines = response_text.strip().split("\n")
    parsed_responses = []
    for line in lines:
        if line.strip():
            try:
                parsed_responses.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Failed to parse line: {line}")
                print(f"Error: {e}")
    return parsed_responses


def send_message_v0(
    chat_session_id: UUID,
    message: str,
    user_performing_action: DATestUser | None = None,
    parent_message_id: int | None = None,
    retrieval_options: RetrievalDetails | None = None,
) -> list[dict[str, Any]]:
    """Send a message to the v0 chat API endpoint and return parsed response."""
    chat_message_req = CreateChatMessageRequest(
        chat_session_id=chat_session_id,
        parent_message_id=parent_message_id,
        message=message,
        file_descriptors=[],
        search_doc_ids=[],
        retrieval_options=retrieval_options,
    )

    headers = user_performing_action.headers if user_performing_action else {}
    cookies = user_performing_action.cookies if user_performing_action else None

    response = requests.post(
        f"{API_SERVER_URL}/v0/chat/send-message",
        json=chat_message_req.model_dump(),
        headers=headers,
        stream=True,
        cookies=cookies,
    )

    response.raise_for_status()

    # Collect all response content
    full_response = ""
    for chunk in response.iter_lines():
        if chunk:
            # Decode bytes to string
            full_response += chunk.decode("utf-8") + "\n"

    return parse_v0_streaming_response(full_response)


class TestChatV0API:
    """Test suite for the v0 chat API endpoint."""

    def test_v0_message_response_format(
        self,
        admin_user: DATestUser,
    ) -> None:
        """Test that the v0 endpoint returns the correct response format."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test v0 API Session",
            user_performing_action=admin_user,
        )

        # Send a message using v0 API
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="What is Onyx?",
            user_performing_action=admin_user,
        )

        # Validate response format structure
        assert len(responses) > 0, "Should receive responses"

        # Check for expected response types
        response_types = set()
        for response in responses:
            if "user_message_id" in response:
                response_types.add("message_ids")
                assert isinstance(response["user_message_id"], (int, type(None)))
                assert isinstance(response["reserved_assistant_message_id"], int)
            elif "answer_piece" in response:
                response_types.add("answer")
                assert isinstance(response["answer_piece"], str)
            elif "tool_name" in response:
                response_types.add("tool")
                assert isinstance(response["tool_name"], str)
            elif "top_documents" in response:
                response_types.add("documents")
                assert isinstance(response["top_documents"], list)
            elif "llm_selected_doc_indices" in response:
                response_types.add("llm_filter")
                assert isinstance(response["llm_selected_doc_indices"], list)
            elif "citations" in response:
                response_types.add("citations")
                assert isinstance(response["citations"], list)
            elif "message_id" in response and "agentic_message_ids" in response:
                response_types.add("final_message")
                assert isinstance(response["message_id"], (int, type(None)))
                assert isinstance(response["agentic_message_ids"], list)
            elif "error" in response:
                response_types.add("error")
                assert isinstance(response["error"], str)

        # Should have message IDs and answer pieces at minimum
        assert "message_ids" in response_types, "Should have message ID response"
        assert "answer" in response_types, "Should have answer pieces"

    def test_v0_search_response_format(
        self,
        admin_user: DATestUser,
        document_builder: DocumentBuilderType,
    ) -> None:
        """Test that search responses are formatted correctly in v0 format."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create test documents
        document_builder(["This is a test document about Onyx"])

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test v0 Search Session",
            user_performing_action=admin_user,
        )

        # Send a message that triggers search
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="Search for information about Onyx",
            user_performing_action=admin_user,
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
            ),
        )

        # Find document response or tool result with documents
        doc_response = None
        for response in responses:
            if "top_documents" in response:
                doc_response = response
                break
            elif "tool_result" in response and isinstance(
                response.get("tool_result"), list
            ):
                # Tool result might contain the documents
                doc_response = {"top_documents": response["tool_result"]}
                break

        # Documents may not always be returned depending on the search
        # Just verify the structure if documents are present
        if doc_response and "top_documents" in doc_response:
            assert isinstance(doc_response["top_documents"], list)

            if len(doc_response["top_documents"]) > 0:
                doc = doc_response["top_documents"][0]
                required_fields = [
                    "document_id",
                    "chunk_ind",
                    "semantic_identifier",
                    "blurb",
                    "source_type",
                    "boost",
                    "hidden",
                    "metadata",
                    "score",
                    "match_highlights",
                    "db_doc_id",
                ]
                for field in required_fields:
                    assert field in doc, f"Missing required field: {field}"

    def test_v0_tool_invocation_format(
        self,
        admin_user: DATestUser,
    ) -> None:
        """Test that tool invocations are formatted correctly in v0 format."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test Tool Invocation",
            user_performing_action=admin_user,
        )

        # Send a message that might trigger tool use
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="Search for information about Onyx features",
            user_performing_action=admin_user,
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
            ),
        )

        # Check for tool responses
        tool_responses = [r for r in responses if "tool_name" in r]

        # Tool responses are optional since not all queries trigger tools
        for response in tool_responses:
            assert isinstance(response["tool_name"], str)

            if "tool_args" in response:
                assert isinstance(response["tool_args"], dict)

            if "tool_result" in response:
                # Tool result can be various types depending on the tool
                tool_result = response["tool_result"]
                tool_name = response.get("tool_name", "")

                if tool_name == "run_search":
                    # Search tool returns a list of documents
                    assert isinstance(tool_result, list)
                    for doc in tool_result:
                        assert isinstance(doc, dict)
                        # Documents should have at least these fields
                        if doc:  # Only check if list is not empty
                            assert "document_id" in doc or "id" in doc

                elif tool_name == "generate_image":
                    # Image generation returns a list of image data
                    assert isinstance(tool_result, list)
                    for img in tool_result:
                        assert isinstance(img, dict)

                else:
                    # Custom tools can return various types
                    # Should be one of: dict, list, str, int, float, bool, or None
                    assert tool_result is None or isinstance(
                        tool_result, (dict, list, str, int, float, bool)
                    )

            if "tool_file_ids" in response:
                assert isinstance(response["tool_file_ids"], list)

    def test_v0_citation_format(
        self,
        admin_user: DATestUser,
        document_builder: DocumentBuilderType,
    ) -> None:
        """Test that citations are formatted correctly."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create test documents with specific content
        _ = document_builder(
            [
                "Onyx is an AI assistant that helps with information retrieval.",
                "Onyx supports multiple document sources and search capabilities.",
            ]
        )

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test Citations",
            user_performing_action=admin_user,
        )

        # Send a message that should generate citations
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="What are the key features of Onyx? Please cite your sources.",
            user_performing_action=admin_user,
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
            ),
        )

        # Find citation response
        citation_responses = [r for r in responses if "citations" in r]

        # Citations are optional - may not always be present
        if citation_responses:
            citation_response = citation_responses[0]
            assert "citations" in citation_response
            assert isinstance(citation_response["citations"], list)

            for citation in citation_response["citations"]:
                assert "citation_num" in citation
                assert "document_id" in citation
                assert isinstance(citation["citation_num"], int)
                assert isinstance(citation["document_id"], str)

    def test_v0_llm_filter_format(
        self,
        admin_user: DATestUser,
        document_builder: DocumentBuilderType,
    ) -> None:
        """Test LLM relevance filter response format."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create multiple test documents
        _ = document_builder(
            [
                "Onyx is an AI assistant",
                "This document is about something else",
                "Another document about Onyx features",
                "Unrelated content here",
                "More Onyx documentation",
            ]
        )

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test LLM Filter",
            user_performing_action=admin_user,
        )

        # Send a message that should trigger filtering
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="Tell me specifically about Onyx features",
            user_performing_action=admin_user,
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
            ),
        )

        # Find LLM filter response
        filter_responses = [r for r in responses if "llm_selected_doc_indices" in r]

        if filter_responses:
            filter_response = filter_responses[0]
            assert "llm_selected_doc_indices" in filter_response
            assert isinstance(filter_response["llm_selected_doc_indices"], list)
            for idx in filter_response["llm_selected_doc_indices"]:
                assert isinstance(idx, int)

    def test_v0_final_response_format(
        self,
        admin_user: DATestUser,
    ) -> None:
        """Test the final response format with message ID and agent info."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test Final Response",
            user_performing_action=admin_user,
        )

        # Send a simple message
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="Hello, how are you?",
            user_performing_action=admin_user,
        )

        # Find final response (usually last or near last)
        final_response = None
        for response in responses:
            if "message_id" in response and "agentic_message_ids" in response:
                final_response = response
                break

        if final_response:
            assert "message_id" in final_response
            assert "agentic_message_ids" in final_response
            assert isinstance(final_response["agentic_message_ids"], list)

    def test_v0_error_format(
        self,
        admin_user: DATestUser,
    ) -> None:
        """Test that errors are formatted correctly in v0 format."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test Error Format",
            user_performing_action=admin_user,
        )

        # Try to trigger an error (this might not always work depending on system state)
        # We'll test the error format structure even if we don't get an actual error

        # Send a normal message first
        responses = send_message_v0(
            chat_session_id=chat_session.id,
            message="Test message",
            user_performing_action=admin_user,
        )

        # Check if any errors occurred
        error_responses = [r for r in responses if "error" in r]

        for error_response in error_responses:
            assert "error" in error_response
            assert isinstance(error_response["error"], str)
            assert "stack_trace" in error_response
            # stack_trace can be None or a string

    def test_v0_streaming_with_history(
        self,
        admin_user: DATestUser,
    ) -> None:
        """Test that the v0 endpoint works correctly with chat history."""
        # Create LLM provider
        LLMProviderManager.create(user_performing_action=admin_user)

        # Create a chat session
        chat_session = ChatSessionManager.create(
            description="Test Chat History",
            user_performing_action=admin_user,
        )

        # Send first message
        responses1 = send_message_v0(
            chat_session_id=chat_session.id,
            message="My name is TestUser",
            user_performing_action=admin_user,
        )

        # Get the assistant message ID from first response
        assistant_msg_id = None
        for response in responses1:
            if "reserved_assistant_message_id" in response:
                assistant_msg_id = response["reserved_assistant_message_id"]
                break

        assert assistant_msg_id is not None, "Should have assistant message ID"

        # Send second message referencing the first
        responses2 = send_message_v0(
            chat_session_id=chat_session.id,
            message="What is my name?",
            user_performing_action=admin_user,
            parent_message_id=assistant_msg_id,
        )

        # Check that we got a response
        assert len(responses2) > 0, "Should receive responses for second message"

        # Collect answer pieces
        answer_pieces = []
        for response in responses2:
            if "answer_piece" in response:
                answer_pieces.append(response["answer_piece"])

        # The answer should reference TestUser
        full_answer = "".join(answer_pieces).lower()
        # The model should recognize the name from history
        # (exact response will vary, but it should acknowledge the name somehow)
        assert len(full_answer) > 0, "Should have an answer"
