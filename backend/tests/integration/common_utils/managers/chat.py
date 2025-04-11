import json
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
        prompt_id: int | None = None,
        search_doc_ids: list[int] | None = None,
        retrieval_options: RetrievalDetails | None = None,
        query_override: str | None = None,
        regenerate: bool | None = None,
        llm_override: LLMOverride | None = None,
        prompt_override: PromptOverride | None = None,
        alternate_assistant_id: int | None = None,
        use_existing_user_message: bool = False,
    ) -> StreamedResponse:
        chat_message_req = CreateChatMessageRequest(
            chat_session_id=chat_session_id,
            parent_message_id=parent_message_id,
            message=message,
            file_descriptors=file_descriptors or [],
            prompt_id=prompt_id,
            search_doc_ids=search_doc_ids or [],
            retrieval_options=retrieval_options,
            rerank_settings=None,  # Can be added if needed
            query_override=query_override,
            regenerate=regenerate,
            llm_override=llm_override,
            prompt_override=prompt_override,
            alternate_assistant_id=alternate_assistant_id,
            use_existing_user_message=use_existing_user_message,
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
        response_data = [
            json.loads(line.decode("utf-8")) for line in response.iter_lines() if line
        ]

        analyzed = StreamedResponse()

        for data in response_data:
            if "rephrased_query" in data:
                analyzed.rephrased_query = data["rephrased_query"]
            if "tool_name" in data:
                analyzed.tool_name = data["tool_name"]
                analyzed.tool_result = (
                    data.get("tool_result")
                    if analyzed.tool_name == "run_search"
                    else None
                )
            if "relevance_summaries" in data:
                analyzed.relevance_summaries = data["relevance_summaries"]
            if "answer_piece" in data and data["answer_piece"]:
                analyzed.full_message += data["answer_piece"]
            if "top_documents" in data:
                assert (
                    analyzed.top_documents is None
                ), "top_documents should only be set once"
                analyzed.top_documents = [
                    SavedSearchDoc(**doc) for doc in data["top_documents"]
                ]

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
