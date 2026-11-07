"""Conversation storage for one chat response and its visible agent history.

Both backends retain PostgreSQL usage rows. Redis holds temporary conversation content.
Execution ownership and checkpoints belong to ChatRunStore.
"""

from typing import Protocol
from uuid import UUID

from onyx.agents.models import AgentInfo
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.chat_utils import omit_prior_tool_result_content
from onyx.chat.incognito_context import (
    load_incognito_context,
    save_incognito_response,
    save_incognito_user_message,
)
from onyx.chat.models import (
    ChatBranch,
    ChatResponseSnapshot,
    ResponseRecord,
    SavedAgentContext,
)
from onyx.chat.response import restore_response_sources
from onyx.db.chat_response import save_chat_response_to_db
from onyx.db.chat_subagents import (
    load_agent_history,
    load_saved_response,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    UserMessage,
)


class ChatHistoryStore(Protocol):
    """Persist conversation content; chat owns message-tree metadata and session execution."""

    message_id: int
    chat_session_id: UUID

    def list_agents(self) -> list[AgentInfo]: ...

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None: ...

    def load_agent_history(self, agent_id: str) -> SavedAgentContext: ...

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None: ...

    def prepare_messages(
        self,
        messages: list[Message],
        previous_run_id: str | None,
        accepted_text: str | None,
    ) -> tuple[list[Message], str | None]:
        """Resolve history without writing content; keep an accepted user message last."""
        ...

    def save_user_message(self, message: UserMessage) -> None: ...

    def save_response(self, response: ChatResponseSnapshot) -> None: ...


class PostgresChatHistoryStore(ChatHistoryStore):
    def __init__(
        self,
        *,
        message_id: int,
        chat_session_id: UUID,
        branch: ChatBranch | None = None,
    ) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id
        self.branch = branch

    def list_agents(self) -> list[AgentInfo]:
        return load_session_agent_metadata(
            self.message_id, branch=self.branch, include_root=False
        )

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return lookup_session_agent(self.message_id, agent_id, parent_id)

    def load_agent_history(self, agent_id: str) -> SavedAgentContext:
        return load_agent_history(self.message_id, agent_id)

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None:
        if not run_id.isdecimal():
            return None
        return load_saved_response(self.message_id, int(run_id), parent_id)

    def prepare_messages(
        self,
        messages: list[Message],
        previous_run_id: str | None,
        accepted_text: str | None,  # noqa: ARG002 -- Already saved during preparation.
    ) -> tuple[list[Message], str | None]:
        # Database history and files were loaded together during preparation.
        return messages, previous_run_id

    def save_user_message(self, message: UserMessage) -> None:  # noqa: ARG002
        """The chat message row already contains the accepted user text."""

    def save_response(self, response: ChatResponseSnapshot) -> None:
        save_chat_response_to_db(
            message_id=self.message_id,
            chat_session_id=self.chat_session_id,
            expected_persist_content=True,
            response=response,
        )


class RedisChatHistoryStore(ChatHistoryStore):
    def __init__(
        self,
        *,
        message_id: int,
        chat_session_id: UUID,
        admission: ChatTurnAdmission | None = None,
    ) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id
        self.admission = admission

    def list_agents(self) -> list[AgentInfo]:
        return []

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:  # noqa: ARG002 -- Incognito has no subagents.
        return None

    def load_agent_history(self, agent_id: str) -> SavedAgentContext:  # noqa: ARG002 -- Incognito has no subagents.
        raise ValueError("Subagents are not available in incognito")

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None:  # noqa: ARG002 -- Incognito has no subagents.
        return None

    def prepare_messages(
        self,
        messages: list[Message],
        previous_run_id: str | None,  # noqa: ARG002 -- Redis holds the previous run.
        accepted_text: str | None,
    ) -> tuple[list[Message], str | None]:
        stored = load_incognito_context(self.chat_session_id)
        if (
            accepted_text is not None
            and messages
            and isinstance(messages[-1], UserMessage)
        ):
            current_user = messages[-1].model_copy(update={"content": accepted_text})
            return (
                omit_prior_tool_result_content(stored.messages) + [current_user],
                stored.previous_run_id,
            )
        selected_id = f"chat:{self.message_id}"
        for index, message in enumerate(stored.messages):
            if isinstance(message, UserMessage) and message.id == selected_id:
                # The cache tracks only the latest run, which regeneration replaces.
                return omit_prior_tool_result_content(
                    stored.messages[: index + 1]
                ), None
        raise ValueError("The selected question is no longer in temporary chat history")

    def save_user_message(self, message: UserMessage) -> None:
        if self.admission is None:
            raise ValueError("Temporary history writes require chat turn admission")
        save_incognito_user_message(
            self.chat_session_id, message, admission=self.admission
        )

    def save_response(self, response: ChatResponseSnapshot) -> None:
        if self.admission is None:
            raise ValueError("Temporary history writes require chat turn admission")
        answer = save_chat_response_to_db(
            message_id=self.message_id,
            chat_session_id=self.chat_session_id,
            expected_persist_content=False,
            response=response,
        )
        messages: list[Message] = (
            response.response.messages
            if response.response and response.response.messages
            else [AssistantMessage(content=[TextContent(text=answer)])]
        )
        if response.response is not None:
            documents = {
                **{doc.document_id: doc for doc in response.citation_to_doc.values()},
                **response.all_search_docs,
            }
            restore_response_sources(messages, documents, response.presentation)
        save_incognito_response(
            self.chat_session_id,
            response.response.run_id if response.response is not None else None,
            admission=self.admission,
            message_id=self.message_id,
            messages=messages,
        )


def get_chat_history_store(
    *,
    message_id: int,
    chat_session_id: UUID,
    persist_content: bool,
    branch: ChatBranch | None = None,
    admission: ChatTurnAdmission | None = None,
) -> ChatHistoryStore:
    if persist_content:
        return PostgresChatHistoryStore(
            message_id=message_id, chat_session_id=chat_session_id, branch=branch
        )
    return RedisChatHistoryStore(
        message_id=message_id,
        chat_session_id=chat_session_id,
        admission=admission,
    )
