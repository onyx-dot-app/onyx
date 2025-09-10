import json
from typing import Any
from typing import cast
from uuid import UUID

import requests
from requests.models import Response

from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SavedSearchDoc
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestChatMessage
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import StreamedResponse
from tests.integration.common_utils.test_models import ToolName
from tests.integration.common_utils.test_models import ToolResult


class ChatSessionManager:
    @staticmethod
    def create(
        persona_id: int = 0,
        description: str = "Test chat session",
        user_performing_action: DATestUser | None = None,
    ) -> DATestChatSession:
        chat_session_creation_req = ChatSessionCreationRequest(
            persona_id=persona_id, description=description
        )
        response = requests.post(
            f"{API_SERVER_URL}/chat/create-chat-session",
            json=chat_session_creation_req.model_dump(),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        chat_session_id = response.json()["chat_session_id"]
        return DATestChatSession(
            id=chat_session_id, persona_id=persona_id, description=description
        )

    @staticmethod
    def send_message(
        chat_session_id: UUID,
        message: str,
        parent_message_id: int | None = None,
        user_performing_action: DATestUser | None = None,
        file_descriptors: list[FileDescriptor] = [],
        search_doc_ids: list[int] | None = None,
        retrieval_options: RetrievalDetails | None = None,
        query_override: str | None = None,
        regenerate: bool | None = None,
        llm_override: LLMOverride | None = None,
        prompt_override: PromptOverride | None = None,
        alternate_assistant_id: int | None = None,
        use_existing_user_message: bool = False,
        use_agentic_search: bool = False,
    ) -> StreamedResponse:
        chat_message_req = CreateChatMessageRequest(
            chat_session_id=chat_session_id,
            parent_message_id=parent_message_id,
            message=message,
            file_descriptors=file_descriptors or [],
            search_doc_ids=search_doc_ids or [],
            retrieval_options=retrieval_options,
            rerank_settings=None,  # Can be added if needed
            query_override=query_override,
            regenerate=regenerate,
            llm_override=llm_override,
            prompt_override=prompt_override,
            alternate_assistant_id=alternate_assistant_id,
            use_existing_user_message=use_existing_user_message,
            use_agentic_search=use_agentic_search,
        )

        headers = (
            user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS
        )
        cookies = user_performing_action.cookies if user_performing_action else None

        response = requests.post(
            f"{API_SERVER_URL}/chat/send-message",
            json=chat_message_req.model_dump(),
            headers=headers,
            stream=True,
            cookies=cookies,
        )

        return ChatSessionManager.analyze_response(response)

    @staticmethod
    def analyze_response(response: Response) -> StreamedResponse:
        response_data = cast(
            list[dict[str, Any]],
            [
                json.loads(line.decode("utf-8"))
                for line in response.iter_lines()
                if line
            ],
        )

        analyzed = StreamedResponse()

        ind_to_tool_use: dict[int, ToolResult] = {}

        for data in response_data:
            if not (data_obj := data.get("obj")):
                continue

            if not (packet_type := data_obj.get("type")):
                continue

            if packet_type == "message_start":
                analyzed.top_documents = [
                    SavedSearchDoc(**doc) for doc in data_obj["final_documents"]
                ]
                analyzed.full_message = data_obj["content"]
                continue

            if packet_type == "message_delta":
                analyzed.full_message += data_obj["content"]
                continue

            if not (ind := data.get("ind")):
                continue

            if packet_type == "internal_search_tool_start":
                if data_obj.get("is_internet_search", False):
                    ind_to_tool_use[ind] = ToolResult(
                        tool_name=ToolName.INTERNET_SEARCH,
                    )
                else:
                    ind_to_tool_use[ind] = ToolResult(
                        tool_name=ToolName.INTERNAL_SEARCH,
                    )
                continue

            if packet_type == "image_generation_tool_start":
                ind_to_tool_use[ind] = ToolResult(
                    tool_name=ToolName.IMAGE_GENERATION,
                )
                continue

            if packet_type == "image_generation_tool_heartbeat":
                # Track heartbeat packets for debugging/testing
                analyzed.heartbeat_packets.append(data)
                continue

            if packet_type == "internal_search_tool_delta":
                ind_to_tool_use[ind].queries.extend(data_obj.get("queries", []))

                documents = data_obj.get("documents", [])
                ind_to_tool_use[ind].documents.extend(
                    [SavedSearchDoc(**doc) for doc in documents]
                )
                continue

        analyzed.used_tools = list(ind_to_tool_use.values())

        return analyzed

    @staticmethod
    def get_chat_history(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestChatMessage]:
        response = requests.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

        return [
            DATestChatMessage(
                id=msg["message_id"],
                chat_session_id=chat_session.id,
                parent_message_id=msg.get("parent_message"),
                message=msg["message"],
            )
            for msg in response.json()["messages"]
        ]

    @staticmethod
    def create_chat_message_feedback(
        message_id: int,
        is_positive: bool,
        user_performing_action: DATestUser | None = None,
        feedback_text: str | None = None,
        predefined_feedback: str | None = None,
    ) -> None:
        response = requests.post(
            url=f"{API_SERVER_URL}/chat/create-chat-message-feedback",
            json={
                "chat_message_id": message_id,
                "is_positive": is_positive,
                "feedback_text": feedback_text,
                "predefined_feedback": predefined_feedback,
            },
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Delete a chat session and all its related records (messages, agent data, etc.)
        Uses the default deletion method configured on the server.

        Returns True if deletion was successful, False otherwise.
        """
        response = requests.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        return response.ok

    @staticmethod
    def soft_delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Soft delete a chat session (marks as deleted but keeps in database).

        Returns True if deletion was successful, False otherwise.
        """
        # Since there's no direct API for soft delete, we'll use a query parameter approach
        # or make a direct call with hard_delete=False parameter via a new endpoint
        response = requests.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}?hard_delete=false",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        return response.ok

    @staticmethod
    def hard_delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Hard delete a chat session (completely removes from database).

        Returns True if deletion was successful, False otherwise.
        """
        response = requests.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}?hard_delete=true",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        return response.ok

    @staticmethod
    def verify_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Verify that a chat session has been deleted by attempting to retrieve it.

        Returns True if the chat session is confirmed deleted, False if it still exists.
        """
        response = requests.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        # Chat session should return 400 if it doesn't exist
        return response.status_code == 400

    @staticmethod
    def verify_soft_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Verify that a chat session has been soft deleted (marked as deleted but still in DB).

        Returns True if the chat session is soft deleted, False otherwise.
        """
        # Try to get the chat session with include_deleted=true
        response = requests.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}?include_deleted=true",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )

        if response.status_code == 200:
            # Chat exists, check if it's marked as deleted
            chat_data = response.json()
            return chat_data.get("deleted", False) is True
        return False

    @staticmethod
    def verify_hard_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """
        Verify that a chat session has been hard deleted (completely removed from DB).

        Returns True if the chat session is hard deleted, False otherwise.
        """
        # Try to get the chat session with include_deleted=true
        response = requests.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}?include_deleted=true",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )

        # For hard delete, even with include_deleted=true, the record should not exist
        return response.status_code != 200
