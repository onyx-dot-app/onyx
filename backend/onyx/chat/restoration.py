"""Explicit payload types used by feature-owned execution checkpoints."""

import hashlib
from io import BytesIO
from uuid import UUID

from pydantic import BaseModel

from onyx.agents.models import ExecutionCheckpoint, RunState
from onyx.agents.runtime import Agent
from onyx.chat.agent import ChatAgent
from onyx.chat.artifacts import ChatSearchResult
from onyx.chat.context import ChatReminders
from onyx.chat.llm_step import PromptMetadata
from onyx.chat.models import ChatFeatureState, ChatMessageMetadata
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.configs.constants import FileOrigin
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.agent import DeepResearchAgent, DeepResearchFeatureState
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchMessageMetadata,
)
from onyx.deep_research.research_agent import ResearchAgent, ResearchFeatureState
from onyx.file_store.constants import AGENT_CHECKPOINT_FILE_PREFIX
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import Message, ToolResult
from onyx.tools.file_snapshot import SavedChatFile
from onyx.tools.interface import Tool
from onyx.tools.models import (
    CustomToolCallSummary,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
)
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
)


def feature_payload_types() -> dict[str, type[BaseModel]]:
    return {
        "chat.state.v1": ChatFeatureState,
        "research.state.v1": ResearchFeatureState,
        "deep_research.state.v1": DeepResearchFeatureState,
        "prompt.metadata.v1": PromptMetadata,
        "chat.metadata.v1": ChatMessageMetadata,
        "chat.search.v1": ChatSearchResult,
        "search.results.v1": SearchDocsResponse,
        "research.metadata.v1": ResearchMessageMetadata,
        "research.result.v1": ResearchAgentCallResult,
        "coding.result.v1": CodingAgentCallResult,
        "tool.custom.v1": CustomToolCallSummary,
        "tool.file_read.v1": FileReadResult,
        "tool.bash.v1": LlmBashExecutionResult,
        "tool.python.v1": LlmPythonExecutionResult,
        "tool.memory.v1": MemoryUpdated,
        "tool.image.v1": FinalImageGenerationResponse,
    }


def restore_chat_agent(
    checkpoint: ExecutionCheckpoint,
    *,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity | None,
) -> Agent:
    """Build feature code and resources; Agent.resume restores saved execution state."""
    snapshot = checkpoint.run_state
    if snapshot.progress is None:
        raise ValueError("Agent restoration requires saved execution progress")
    state = snapshot.progress.feature_state
    context = checkpoint.agent_state.model_copy(deep=True)
    token_counter = get_llm_token_counter(llm)
    if isinstance(state, ChatFeatureState):
        chat = ChatAgent(
            messages=context.messages,
            tools=tools,
            custom_agent_prompt=state.custom_prompt,
            base_system_prompt=state.base_prompt,
            context_files=state.context_files.restore(),
            persona=state.persona,
            user_memory_context=state.memory,
            llm=llm,
            token_counter=token_counter,
            forced_tool_id=state.forced_tool_id,
            user_identity=user_identity,
            reasoning_effort=state.reasoning_effort,
            include_citations=state.include_citations,
            all_injected_file_metadata=state.file_metadata,
            inject_memories_in_prompt=state.inject_memories,
            reminders=ChatReminders(enabled=state.reminders_enabled),
            checkpoint=context.checkpoint,
            previous_run_id=snapshot.previous_run_id,
            agent_id=snapshot.agent_id,
        )
        return chat.agent
    if isinstance(state, ResearchFeatureState):
        return ResearchAgent(
            tools=tools,
            llm=llm,
            token_counter=token_counter,
            user_identity=user_identity,
            language_section=state.configuration.language_section,
            reasoning_effort=state.configuration.reasoning_effort,
            messages=context.messages,
            checkpoint=context.checkpoint,
            previous_run_id=snapshot.previous_run_id,
            agent_id=snapshot.agent_id,
        ).agent
    if isinstance(state, DeepResearchFeatureState):
        return DeepResearchAgent(
            messages=context.messages,
            allowed_tools=tools,
            llm=llm,
            token_counter=token_counter,
            user_identity=user_identity,
            language_section=state.language_section,
            reasoning_effort=state.reasoning_effort,
            all_injected_file_metadata=state.file_metadata,
            skip_clarification=state.skip_clarification,
            checkpoint=context.checkpoint,
            previous_run_id=snapshot.previous_run_id,
            agent_id=snapshot.agent_id,
        ).agent
    raise ValueError("Checkpoint has no supported chat feature state")


def persist_checkpoint_files(
    checkpoint: ExecutionCheckpoint, *, session_id: UUID
) -> None:
    """Replace transient file contents with tenant-scoped file-store references."""

    def save(file: SavedChatFile) -> None:
        if file.file_id is not None:
            file.content = None
            return
        if file.content is None:
            raise ValueError("Checkpoint file is missing its contents")
        file_id = f"{AGENT_CHECKPOINT_FILE_PREFIX}{session_id}/{hashlib.sha256(file.content).hexdigest()}"
        store = get_default_file_store()
        # Concurrent saves use identical bytes for this session-scoped content ID.
        if not store.has_file(file_id, FileOrigin.OTHER, "application/octet-stream"):
            store.save_file(
                content=BytesIO(file.content),
                display_name=file.filename,
                file_origin=FileOrigin.OTHER,
                file_type="application/octet-stream",
                file_metadata={"chat_session_id": str(session_id)},
                file_id=file_id,
            )
        file.file_id = file_id
        file.content = None

    def payload(value: BaseModel | None) -> None:
        if isinstance(value, ChatFeatureState):
            for file in value.chat_files:
                save(file)
        elif isinstance(value, ChatSearchResult):
            for staged in value.staged_files:
                file = SavedChatFile.capture(staged)
                save(file)
                staged.file_id = file.file_id

    def messages(items: list[Message]) -> None:
        for message in items:
            payload(message.metadata)
            if isinstance(message, ToolResult):
                payload(message.details)

    def snapshot(record: RunState) -> None:
        messages(record.input_messages)
        messages(record.messages)
        if record.progress is not None:
            progress = record.progress
            payload(progress.feature_state)
            for answer in progress.human_tool_answers.values():
                if answer.result is not None:
                    payload(answer.result.details)
                    payload(answer.result.metadata)
        for child in record.child_runs:
            snapshot(child)

    messages(checkpoint.agent_state.messages)
    snapshot(checkpoint.run_state)
