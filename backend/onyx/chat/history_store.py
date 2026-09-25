"""Conversation storage for one chat response and its visible agent history.

Both backends retain PostgreSQL usage rows. Redis holds temporary conversation content.
Execution ownership and checkpoints belong to ChatRunStore.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from onyx.agents.models import AgentInfo
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.incognito_context import (
    append_incognito_message,
    get_or_create_incognito_root_id,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_context,
    load_incognito_saved_run,
    lookup_incognito_agent,
    save_incognito_response,
)
from onyx.chat.models import ChatResponseSnapshot, ResponseRecord, SavedAgentContext
from onyx.chat.response_items import messages_from_items
from onyx.db.chat_response import save_chat_response_to_db
from onyx.db.chat_subagents import (
    load_agent_history,
    load_saved_run,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.llm.models import AssistantMessage, Message, TextContent, UserMessage


class ChatHistoryStore(Protocol):
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
        """Resolve history after database messages and attached files have been converted."""
        ...

    def root_agent_id(self, proposed_id: str) -> str: ...

    def save_response(self, response: ChatResponseSnapshot) -> None: ...


class PostgresChatHistoryStore(ChatHistoryStore):
    def __init__(self, *, message_id: int, chat_session_id: UUID) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id

    def list_agents(self) -> list[AgentInfo]:
        return load_session_agent_metadata(self.message_id)

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return lookup_session_agent(self.message_id, agent_id, parent_id)

    def load_agent_history(self, agent_id: str) -> SavedAgentContext:
        return load_agent_history(self.message_id, agent_id)

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None:
        return load_saved_run(self.message_id, run_id, parent_id)

    def prepare_messages(
        self,
        messages: list[Message],
        previous_run_id: str | None,
        accepted_text: str | None,  # noqa: ARG002 -- Already saved during preparation.
    ) -> tuple[list[Message], str | None]:
        # Database history and files were loaded together during preparation.
        return messages, previous_run_id

    def root_agent_id(self, proposed_id: str) -> str:
        return proposed_id

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
        visible_message_ids: Sequence[int],
    ) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id
        self.visible_message_ids = tuple(visible_message_ids)

    def list_agents(self) -> list[AgentInfo]:
        return load_incognito_agent_metadata(
            self.chat_session_id, self.visible_message_ids
        )

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return lookup_incognito_agent(
            self.chat_session_id, self.visible_message_ids, agent_id, parent_id
        )

    def load_agent_history(self, agent_id: str) -> SavedAgentContext:
        return load_incognito_agent_history(
            self.chat_session_id, self.visible_message_ids, agent_id
        )

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None:
        return load_incognito_saved_run(
            self.chat_session_id, self.visible_message_ids, run_id, parent_id
        )

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
            messages = stored.messages + [current_user]
            append_incognito_message(self.chat_session_id, current_user)
        else:
            messages = stored.messages
        return messages, stored.previous_run_id

    def root_agent_id(self, proposed_id: str) -> str:
        return get_or_create_incognito_root_id(self.chat_session_id, proposed_id)

    def save_response(self, response: ChatResponseSnapshot) -> None:
        answer = save_chat_response_to_db(
            message_id=self.message_id,
            chat_session_id=self.chat_session_id,
            expected_persist_content=False,
            response=response,
        )
        messages = (
            messages_from_items(response.response.items)
            if response.response and response.response.items
            else [AssistantMessage(content=[TextContent(text=answer)])]
        )
        sources_by_run: dict[str, CitationMapping] = {}
        if response.response is not None:
            documents = {
                **{doc.document_id: doc for doc in response.citation_to_doc.values()},
                **response.all_search_docs,
            }
            pending = list(response.response.child_runs)
            while pending:
                record = pending.pop()
                sources = sources_by_run.setdefault(record.run_id, {})
                for item in record.items:
                    setting = response.presentation.get(item.id)
                    if setting is None:
                        continue
                    for number, document_id in setting.citation_documents.items():
                        if document_id in documents:
                            sources[number] = documents[document_id]
                pending.extend(record.child_runs)
        save_incognito_response(
            self.chat_session_id,
            response.response,
            sources_by_run,
            message_id=self.message_id,
            messages=messages,
        )


def get_chat_history_store(
    *,
    message_id: int,
    chat_session_id: UUID,
    persist_content: bool,
    visible_message_ids: Sequence[int] = (),
) -> ChatHistoryStore:
    if persist_content:
        return PostgresChatHistoryStore(
            message_id=message_id, chat_session_id=chat_session_id
        )
    return RedisChatHistoryStore(
        message_id=message_id,
        chat_session_id=chat_session_id,
        visible_message_ids=visible_message_ids,
    )
