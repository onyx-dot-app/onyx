import json
from typing import Any
from typing import cast
from typing import Literal
from typing import TypedDict
from uuid import UUID

import requests
from requests.models import Response

from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import StreamingType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestChatMessage
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ErrorResponse
from tests.integration.common_utils.test_models import StreamedResponse
from tests.integration.common_utils.test_models import ToolName
from tests.integration.common_utils.test_models import ToolResult


class StreamPacketObj(TypedDict, total=False):
    """Base structure for streaming packet objects."""

    type: Literal[
        "message_start",
        "message_delta",
        "search_tool_start",
        "search_tool_queries_delta",
        "search_tool_documents_delta",
        "image_generation_start",
        "image_generation_heartbeat",
        "image_generation_final",
    ]
    content: str
    final_documents: list[dict[str, Any]]
    is_internet_search: bool
    images: list[dict[str, Any]]
    queries: list[str]
    documents: list[dict[str, Any]]


class PlacementData(TypedDict, total=False):
    """Structure for packet placement information."""

    turn_index: int
    tab_index: int
    sub_turn_index: int | None


class StreamPacketData(TypedDict, total=False):
    """Structure for streaming response packets."""

    reserved_assistant_message_id: int
    error: str
    stack_trace: str
    obj: StreamPacketObj
    placement: PlacementData


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
        file_descriptors: list[FileDescriptor] | None = None,
        search_doc_ids: list[int] | None = None,
        retrieval_options: RetrievalDetails | None = None,
        query_override: str | None = None,
        regenerate: bool | None = None,
        llm_override: LLMOverride | None = None,
        prompt_override: PromptOverride | None = None,
        alternate_assistant_id: int | None = None,
        use_existing_user_message: bool = False,
        forced_tool_ids: list[int] | None = None,
        chat_session: DATestChatSession | None = None,
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
            forced_tool_ids=forced_tool_ids,
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

        streamed_response = ChatSessionManager.analyze_response(response)

        if not chat_session:
            return streamed_response

        # TODO: ideally we would get the research answer purpose from the chat history
        # but atm the field needed would not be used outside of testing, so we're not adding it.
        # chat_history = ChatSessionManager.get_chat_history(
        #     chat_session=chat_session,
        #     user_performing_action=user_performing_action,
        # )

        # for message_obj in chat_history:
        #     if message_obj.message_type == MessageType.ASSISTANT:
        #         streamed_response.research_answer_purpose = (
        #             message_obj.research_answer_purpose
        #         )
        #         streamed_response.assistant_message_id = message_obj.id
        #         break

        return streamed_response

    @staticmethod
    def send_message_with_disconnect(
        chat_session_id: UUID,
        message: str,
        disconnect_after_packets: int = 0,
        parent_message_id: int | None = None,
        user_performing_action: DATestUser | None = None,
        file_descriptors: list[FileDescriptor] | None = None,
        search_doc_ids: list[int] | None = None,
        retrieval_options: RetrievalDetails | None = None,
        query_override: str | None = None,
        regenerate: bool | None = None,
        llm_override: LLMOverride | None = None,
        prompt_override: PromptOverride | None = None,
        alternate_assistant_id: int | None = None,
        use_existing_user_message: bool = False,
        forced_tool_ids: list[int] | None = None,
    ) -> None:
        """
        Send a message and simulate client disconnect before stream completes.

        This is useful for testing how the server handles client disconnections
        during streaming responses.

        Args:
            chat_session_id: The chat session ID
            message: The message to send
            disconnect_after_packets: Disconnect after receiving this many packets.
                If None, disconnect_after_type must be specified.
            disconnect_after_type: Disconnect after receiving a packet of this type
                (e.g., "message_start", "search_tool_start"). If None,
                disconnect_after_packets must be specified.
            ... (other standard message parameters)

        Returns:
            StreamedResponse containing data received before disconnect,
            with is_disconnected=True flag set.
        """
        chat_message_req = CreateChatMessageRequest(
            chat_session_id=chat_session_id,
            parent_message_id=parent_message_id,
            message=message,
            file_descriptors=file_descriptors or [],
            search_doc_ids=search_doc_ids or [],
            retrieval_options=retrieval_options,
            rerank_settings=None,
            query_override=query_override,
            regenerate=regenerate,
            llm_override=llm_override,
            prompt_override=prompt_override,
            alternate_assistant_id=alternate_assistant_id,
            use_existing_user_message=use_existing_user_message,
            forced_tool_ids=forced_tool_ids,
        )

        headers = (
            user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS
        )
        cookies = user_performing_action.cookies if user_performing_action else None

        packets_received = 0

        with requests.post(
            f"{API_SERVER_URL}/chat/send-message",
            json=chat_message_req.model_dump(),
            headers=headers,
            stream=True,
            cookies=cookies,
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue

                packets_received += 1
                if packets_received > disconnect_after_packets:
                    break

        return None

    @staticmethod
    def analyze_response(response: Response) -> StreamedResponse:
        response_data = cast(
            list[StreamPacketData],
            [
                json.loads(line.decode("utf-8"))
                for line in response.iter_lines()
                if line
            ],
        )
        ind_to_tool_use: dict[int, ToolResult] = {}
        top_documents: list[SearchDoc] = []
        heartbeat_packets: list[StreamPacketData] = []
        full_message = ""
        assistant_message_id: int | None = None
        error = None
        ind: int
        for data in response_data:
            if reserved_id := data.get("reserved_assistant_message_id"):
                assistant_message_id = reserved_id
            elif data.get("error"):
                error = ErrorResponse(
                    error=str(data["error"]),
                    stack_trace=str(data["stack_trace"]),
                )
            elif (
                (data_obj := data.get("obj"))
                and (packet_type := data_obj.get("type"))
                and (
                    ind := cast(
                        int,
                        (
                            data.get("ind")
                            if data.get("ind") is not None
                            else data.get("placement", {}).get("turn_index")
                        ),
                    )
                )
                is not None
            ):
                packet_type_str = str(packet_type)
                if packet_type_str == StreamingType.MESSAGE_START.value:
                    final_docs = data_obj.get("final_documents")
                    if isinstance(final_docs, list):
                        top_documents = [SearchDoc(**doc) for doc in final_docs]
                    full_message += data_obj.get("content", "")
                elif packet_type_str == StreamingType.MESSAGE_DELTA.value:
                    full_message += data_obj["content"]
                elif packet_type_str == StreamingType.SEARCH_TOOL_START.value:
                    tool_name = (
                        ToolName.INTERNET_SEARCH
                        if data_obj.get("is_internet_search", False)
                        else ToolName.INTERNAL_SEARCH
                    )
                    ind_to_tool_use[ind] = ToolResult(
                        tool_name=tool_name,
                    )
                elif packet_type_str == StreamingType.IMAGE_GENERATION_START.value:
                    ind_to_tool_use[ind] = ToolResult(
                        tool_name=ToolName.IMAGE_GENERATION,
                    )
                elif packet_type_str == StreamingType.IMAGE_GENERATION_HEARTBEAT.value:
                    # Track heartbeat packets for debugging/testing
                    heartbeat_packets.append(data)
                elif packet_type_str == StreamingType.IMAGE_GENERATION_FINAL.value:
                    from tests.integration.common_utils.test_models import (
                        GeneratedImage,
                    )

                    images = data_obj.get("images", [])
                    ind_to_tool_use[ind].images.extend(
                        [GeneratedImage(**img) for img in images]
                    )
                elif packet_type_str == StreamingType.SEARCH_TOOL_QUERIES_DELTA.value:
                    ind_to_tool_use[ind].queries.extend(data_obj.get("queries", []))
                elif packet_type_str == StreamingType.SEARCH_TOOL_DOCUMENTS_DELTA.value:
                    docs = []
                    for doc in data_obj.get("documents", []):
                        if "db_doc_id" in doc:
                            # Already a SavedSearchDoc format
                            docs.append(SavedSearchDoc(**doc))
                        else:
                            # SearchDoc format - Convert to SavedSearchDoc
                            search_doc = SearchDoc(**doc)
                            docs.append(
                                SavedSearchDoc.from_search_doc(search_doc, db_doc_id=0)
                            )
                    ind_to_tool_use[ind].documents.extend(docs)
        # If there's an error, assistant_message_id might not be present
        if not assistant_message_id and not error:
            raise ValueError("Assistant message id not found")
        return StreamedResponse(
            full_message=full_message,
            assistant_message_id=assistant_message_id or -1,  # Use -1 for error cases
            top_documents=top_documents,
            used_tools=list(ind_to_tool_use.values()),
            heartbeat_packets=[dict(packet) for packet in heartbeat_packets],
            error=error,
        )

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
                message_type=msg.get("message_type"),
                files=msg.get("files"),
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
