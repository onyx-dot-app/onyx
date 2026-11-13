"""Conversation storage for one chat response and its visible agent history.

Both backends retain PostgreSQL usage rows. Redis holds temporary conversation content.
Execution ownership and checkpoints belong to ChatRunStore.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from onyx.agents.models import AgentInfo, CompactionCheckpoint
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.incognito_context import (
    input_group_start,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_context,
    load_incognito_saved_run,
    lookup_incognito_agent,
    save_incognito_response,
    save_incognito_user_messages,
)
from onyx.chat.models import (
    ChatBranch,
    ChatHistoryResult,
    ChatResponseSnapshot,
    IncognitoAgentResponse,
    IncognitoState,
    PromptMetadata,
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


def _selected_history(
    state: IncognitoState, canonical: Sequence[Message]
) -> tuple[list[Message], IncognitoAgentResponse | None]:
    """Select saved content by the database branch, including a chosen model response."""
    if not state.messages:
        return [], None
    selected_ids = {
        message.id for message in canonical if isinstance(message, UserMessage)
    }
    responses = [
        message for message in canonical if isinstance(message, AssistantMessage)
    ]
    selected_response = None
    retained_ids = {message.id for message in state.messages}
    for message in responses:
        response = state.responses.get((message.id or "").removeprefix("chat:"))
        if (
            response is None
            or not response.message_ids
            or response.message_ids[-1] not in retained_ids
        ):
            # Failed saves and retention can leave a canonical row without content.
            continue
        selected_ids.update(response.message_ids)
        selected_response = response
    return [
        message for message in state.messages if message.id in selected_ids
    ], selected_response


class ChatHistoryStore(Protocol):
    """Persist conversation content; chat owns message-tree metadata and session execution."""

    message_id: int
    chat_session_id: UUID

    def list_agents(self) -> list[AgentInfo]: ...

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None: ...

    def load_agent_history(self, agent_id: str) -> SavedAgentContext: ...

    def load_saved_run(self, run_id: str, parent_id: str) -> ResponseRecord | None: ...

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
        admission: ChatTurnAdmission | None = None,
    ) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id
        self.visible_message_ids = tuple(visible_message_ids)
        self.admission = admission

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
        history: ChatHistoryResult,
        accepted_text: str | None,
    ) -> tuple[ChatHistoryResult, str | None, CompactionCheckpoint | None]:
        stored = load_incognito_context(self.chat_session_id)
        selected_history, selected_response = _selected_history(
            stored, history.messages[: history.input_start]
        )
        current_input = history.messages[history.input_start :]
        current_file_ids = (
            {
                message.metadata.file_id
                for message in current_input
                if isinstance(message.metadata, PromptMetadata)
            }
            if accepted_text is not None
            else set()
        )
        # The branch owns availability; temporary history owns retained text names and sizes.
        history = history.model_copy(
            update={
                "all_injected_file_metadata": {
                    file_id: metadata.model_copy(
                        update={
                            "filename": stored.file_metadata[file_id].filename,
                            "approx_char_count": stored.file_metadata[
                                file_id
                            ].approx_char_count,
                        }
                    )
                    if file_id in stored.file_metadata
                    and file_id not in current_file_ids
                    else metadata
                    for file_id, metadata in history.all_injected_file_metadata.items()
                }
            }
        )
        if accepted_text is not None:
            if not current_input or not isinstance(current_input[-1], UserMessage):
                raise ValueError(
                    "Temporary history requires a question after its attachments"
                )
            current_input = [
                *current_input[:-1],
                current_input[-1].model_copy(update={"content": accepted_text}),
            ]
            return (
                history.model_copy(
                    update={
                        "messages": [*selected_history, *current_input],
                        "input_start": len(selected_history),
                    }
                ),
                selected_response.run_id if selected_response else None,
                selected_response.checkpoint if selected_response else None,
            )
        selected_id = f"chat:{self.message_id}"
        for index, message in enumerate(stored.messages):
            if isinstance(message, UserMessage) and message.id == selected_id:
                # Regeneration reuses the exact saved question and attachment content.
                return (
                    history.model_copy(
                        update={
                            "messages": [
                                *selected_history,
                                *stored.messages[
                                    input_group_start(stored.messages, index) : index
                                    + 1
                                ],
                            ],
                            "input_start": len(selected_history),
                        }
                    ),
                    None,
                    selected_response.checkpoint if selected_response else None,
                )
        raise ValueError("The selected question is no longer in temporary chat history")

    def save_user_messages(self, history: ChatHistoryResult) -> None:
        if self.admission is None:
            raise ValueError("Temporary history writes require chat turn admission")
        save_incognito_user_messages(
            self.chat_session_id,
            history.messages[history.input_start :],
            admission=self.admission,
            file_metadata=history.all_injected_file_metadata,
            history_message_ids=[
                message.id for message in history.messages[: history.input_start]
            ],
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
        sources_by_run: dict[str, CitationMapping] = {}
        if response.response is not None:
            documents = {
                **{doc.document_id: doc for doc in response.citation_to_doc.values()},
                **response.all_search_docs,
            }
            restore_response_sources(messages, documents, response.presentation)
            pending = list(response.response.child_runs)
            while pending:
                record = pending.pop()
                sources = sources_by_run.setdefault(record.run_id, {})
                for message in record.messages:
                    if not isinstance(message, AssistantMessage) or message.id is None:
                        continue
                    setting = response.presentation.get(message.id)
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
            admission=self.admission,
            message_id=self.message_id,
            messages=messages,
        )


def get_chat_history_store(
    *,
    message_id: int,
    chat_session_id: UUID,
    persist_content: bool,
    visible_message_ids: Sequence[int] = (),
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
        visible_message_ids=visible_message_ids,
        admission=admission,
    )
