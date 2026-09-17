from uuid import UUID

import httpx
from pydantic import BaseModel

from onyx.context.search.models import SavedSearchDoc, SearchDoc, SearchDocsResponse
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import (
    AUTO_PLACE_AFTER_LATEST_MESSAGE,
    ChatSessionCreationRequest,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    ChatHeartbeat,
    ItemUpdate,
    PacketIdentity,
    PacketObj,
    TextItem,
    TextPurpose,
    ToolItem,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import (
    DATestChatMessage,
    DATestChatSession,
    DATestUser,
    ErrorResponse,
    StreamedResponse,
    ToolCallDebug,
    ToolName,
    ToolResult,
)


class StreamEnvelope(BaseModel):
    reserved_assistant_message_id: int | None = None
    error: str | None = None
    stack_trace: str | None = None
    obj: PacketObj | None = None
    identity: PacketIdentity | None = None


class ChatSessionManager:
    @staticmethod
    def create(
        user_performing_action: DATestUser,
        persona_id: int = 0,
        description: str = "Test chat session",
        project_id: int | None = None,
    ) -> DATestChatSession:
        chat_session_creation_req = ChatSessionCreationRequest(
            persona_id=persona_id,
            description=description,
            project_id=project_id,
        )
        response = client.post(
            f"{API_SERVER_URL}/chat/create-chat-session",
            json=chat_session_creation_req.model_dump(),
            headers=user_performing_action.headers,
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
        user_performing_action: DATestUser,
        parent_message_id: int | None = None,
        file_descriptors: list[FileDescriptor] | None = None,
        allowed_tool_ids: list[int] | None = None,
        forced_tool_ids: list[int] | None = None,
        chat_session: DATestChatSession | None = None,
        mock_llm_response: str | None = None,
        deep_research: bool = False,
        llm_override: LLMOverride | None = None,
    ) -> StreamedResponse:
        chat_message_req = SendMessageRequest(
            message=message,
            chat_session_id=chat_session_id,
            parent_message_id=(
                parent_message_id
                if parent_message_id is not None
                else AUTO_PLACE_AFTER_LATEST_MESSAGE
            ),
            file_descriptors=file_descriptors or [],
            allowed_tool_ids=allowed_tool_ids,
            forced_tool_id=forced_tool_ids[0] if forced_tool_ids else None,
            mock_llm_response=mock_llm_response,
            deep_research=deep_research,
            llm_override=llm_override,
        )

        with client.stream(
            "POST",
            f"{API_SERVER_URL}/chat/send-chat-message",
            json=chat_message_req.model_dump(mode="json"),
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        ) as response:
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
        #     if message_obj.role == 'assistant':
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
        user_performing_action: DATestUser,
        disconnect_after_packets: int = 0,
        parent_message_id: int | None = None,
        file_descriptors: list[FileDescriptor] | None = None,
        allowed_tool_ids: list[int] | None = None,
        forced_tool_ids: list[int] | None = None,
        mock_llm_response: str | None = None,
        deep_research: bool = False,
        llm_override: LLMOverride | None = None,
    ) -> None:
        """
        Send a message and simulate client disconnect before stream completes.

        This is useful for testing how the server handles client disconnections
        during streaming responses.

        Args:
            chat_session_id: The chat session ID
            message: The message to send
            disconnect_after_packets: Disconnect after receiving this many packets.
            ... (other standard message parameters)

        Returns:
            None. Caller can verify server-side cleanup via get_chat_history etc.
        """
        chat_message_req = SendMessageRequest(
            message=message,
            chat_session_id=chat_session_id,
            parent_message_id=(
                parent_message_id
                if parent_message_id is not None
                else AUTO_PLACE_AFTER_LATEST_MESSAGE
            ),
            file_descriptors=file_descriptors or [],
            allowed_tool_ids=allowed_tool_ids,
            forced_tool_id=forced_tool_ids[0] if forced_tool_ids else None,
            mock_llm_response=mock_llm_response,
            deep_research=deep_research,
            llm_override=llm_override,
        )

        packets_received = 0

        with client.stream(
            "POST",
            f"{API_SERVER_URL}/chat/send-chat-message",
            json=chat_message_req.model_dump(mode="json"),
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue

                packets_received += 1
                if packets_received > disconnect_after_packets:
                    break

        return None

    @staticmethod
    def analyze_response(response: httpx.Response) -> StreamedResponse:
        tools: dict[tuple[str, str], ToolItem] = {}
        top_documents: list[SearchDoc] = []
        heartbeat_packets: list[StreamEnvelope] = []
        full_message = ""
        assistant_message_id: int | None = None
        error = None
        for line in response.iter_lines():
            if not line:
                continue
            envelope = StreamEnvelope.model_validate_json(line)
            if envelope.reserved_assistant_message_id is not None:
                assistant_message_id = envelope.reserved_assistant_message_id
            if envelope.error:
                error = ErrorResponse(
                    error=envelope.error, stack_trace=envelope.stack_trace or ""
                )
            if isinstance(envelope.obj, ChatHeartbeat):
                heartbeat_packets.append(envelope)
            if not isinstance(envelope.obj, ItemUpdate) or envelope.identity is None:
                continue
            item = envelope.obj.item
            if (
                isinstance(item, TextItem)
                and item.purpose == TextPurpose.ANSWER
                and envelope.identity.parent_run_id is None
            ):
                full_message = item.text
                top_documents = item.documents
            elif (
                isinstance(item, ToolItem)
                and envelope.identity.tool_call_id is not None
            ):
                tools[
                    (envelope.identity.message_id, envelope.identity.tool_call_id)
                ] = item
        if assistant_message_id is None and error is None:
            raise ValueError("Assistant message id not found")
        used_tools: list[ToolResult] = []
        for item in tools.values():
            if item.name not in {name.value for name in ToolName}:
                continue
            result = ToolResult(tool_name=ToolName(item.name))
            if isinstance(item.metadata, SearchDocsResponse):
                result.queries = item.metadata.queries
                result.documents = [
                    SavedSearchDoc.from_search_doc(doc, db_doc_id=0)
                    for doc in item.metadata.displayed_docs or item.metadata.search_docs
                ]
            elif isinstance(item.metadata, FinalImageGenerationResponse):
                result.images = item.metadata.generated_images
            used_tools.append(result)
        return StreamedResponse(
            full_message=full_message,
            assistant_message_id=assistant_message_id
            if assistant_message_id is not None
            else -1,
            top_documents=top_documents,
            used_tools=used_tools,
            tool_call_debug=[
                ToolCallDebug(
                    tool_call_id=key[1], tool_name=item.name, tool_args=item.arguments
                )
                for key, item in tools.items()
            ],
            heartbeat_packets=[
                packet.model_dump(mode="json") for packet in heartbeat_packets
            ],
            error=error,
        )

    @staticmethod
    def get_chat_history(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> list[DATestChatMessage]:
        response = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            headers=user_performing_action.headers,
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
        user_performing_action: DATestUser,
        feedback_text: str | None = None,
        predefined_feedback: str | None = None,
    ) -> None:
        response = client.post(
            url=f"{API_SERVER_URL}/chat/create-chat-message-feedback",
            json={
                "chat_message_id": message_id,
                "is_positive": is_positive,
                "feedback_text": feedback_text,
                "predefined_feedback": predefined_feedback,
            },
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Delete a chat session and all its related records (messages, agent data, etc.)
        Uses the default deletion method configured on the server.

        Returns True if deletion was successful, False otherwise.
        """
        response = client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}",
            headers=user_performing_action.headers,
        )
        return not response.is_error

    @staticmethod
    def soft_delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Soft delete a chat session (marks as deleted but keeps in database).

        Returns True if deletion was successful, False otherwise.
        """
        # Since there's no direct API for soft delete, we'll use a query parameter approach
        # or make a direct call with hard_delete=False parameter via a new endpoint
        response = client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}?hard_delete=false",
            headers=user_performing_action.headers,
        )
        return not response.is_error

    @staticmethod
    def hard_delete(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Hard delete a chat session (completely removes from database).

        Returns True if deletion was successful, False otherwise.
        """
        response = client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session.id}?hard_delete=true",
            headers=user_performing_action.headers,
        )
        return not response.is_error

    @staticmethod
    def verify_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Verify that a chat session has been deleted by attempting to retrieve it.

        Returns True if the chat session is confirmed deleted, False if it still exists.
        """
        response = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            headers=user_performing_action.headers,
        )
        # Chat session should return 404 if it doesn't exist or is deleted
        return response.status_code == 404

    @staticmethod
    def verify_soft_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Verify that a chat session has been soft deleted (marked as deleted but still in DB).

        Returns True if the chat session is soft deleted, False otherwise.
        """
        # Try to get the chat session with include_deleted=true
        response = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}?include_deleted=true",
            headers=user_performing_action.headers,
        )

        if response.status_code == 200:
            # Chat exists, check if it's marked as deleted
            chat_data = response.json()
            return chat_data.get("deleted", False) is True
        return False

    @staticmethod
    def verify_hard_deleted(
        chat_session: DATestChatSession,
        user_performing_action: DATestUser,
    ) -> bool:
        """
        Verify that a chat session has been hard deleted (completely removed from DB).

        Returns True if the chat session is hard deleted, False otherwise.
        """
        # Try to get the chat session with include_deleted=true
        response = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}?include_deleted=true",
            headers=user_performing_action.headers,
        )

        # For hard delete, even with include_deleted=true, the record should not exist
        return response.status_code != 200
