"""Rebuild chat agents and persist file resources needed to resume them."""

import hashlib
from collections.abc import Callable
from io import BytesIO
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from onyx.agents.agent_coordination import MAX_CHILD_DEPTH
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunState
from onyx.agents.runtime import Agent
from onyx.chat.agent import ChatAgent, build_chat_agent
from onyx.chat.models import (
    ChatFeatureState,
    ChatMessageMetadata,
    ChatTurnSetup,
    SavedAgentContext,
    StagedChatFiles,
)
from onyx.configs.constants import FileOrigin
from onyx.db.chat_response import CHECKPOINT_DUMP_CLEANUP
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.models import (
    DeepResearchFeatureState,
    ResearchConfiguration,
    ResearchFeatureState,
)
from onyx.deep_research.research_agent import ResearchAgent
from onyx.file_store.constants import AGENT_CHECKPOINT_FILE_PREFIX
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import AssistantMessage, Message, ToolResult
from onyx.tools.file_snapshot import SavedChatFile
from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.subagents.models import ChatConfiguration
from onyx.tools.tool_implementations.subagents.subagent_tools import ListAgentsTool

_FEATURE_STATE = TypeAdapter(
    Annotated[
        ChatFeatureState | ResearchFeatureState | DeepResearchFeatureState,
        Field(discriminator="kind"),
    ]
)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def restore_subagent(
    history: SavedAgentContext,
    depth: int,
    *,
    setup: ChatTurnSetup,
    llm: LLM,
    tools: list[Tool],
    inject_memories: bool,
) -> Agent:
    """Rebuild a saved child conversation with this request's authorized resources."""
    configuration = history.configuration
    if isinstance(configuration, ChatConfiguration):
        if history.sources:
            for message in reversed(history.messages):
                if isinstance(message, AssistantMessage):
                    message.metadata = ChatMessageMetadata(sources=history.sources)
                    break
        return build_chat_agent(
            AgentState(messages=history.messages, checkpoint=history.checkpoint),
            history.agent_id,
            history.previous_run_id,
            setup=setup,
            llm=llm,
            tools=tools,
            inject_memories=inject_memories,
            with_subagents=True,
            is_subagent=True,
            depth=depth,
        )
    if isinstance(configuration, ResearchConfiguration):
        return ResearchAgent(
            agent_id=history.agent_id,
            messages=history.messages,
            checkpoint=history.checkpoint,
            previous_run_id=history.previous_run_id,
            sources=history.sources,
            tools=tools,
            llm=llm,
            token_counter=get_llm_token_counter(llm),
            user_identity=setup.user_identity,
            language_section=configuration.language_section,
            reasoning_effort=configuration.reasoning_effort,
        )
    raise ValueError("This agent's external resources are no longer available")


def restore_chat_agent(
    checkpoint: ExecutionCheckpoint,
    depth: int,
    *,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity | None,
    subagent_factory: Callable[[int], Callable[[], Agent]],
) -> Agent:
    """Build feature code and resources; Agent.resume restores saved execution state.

    `depth` counts the agent's levels below the root. A chat agent gets the
    agent tools when it had them: every subagent, and a root whose saved step
    declared them. Its children are one level deeper (`subagent_factory`); an
    agent at `MAX_CHILD_DEPTH` cannot start agents.
    """
    snapshot = checkpoint.run_state
    if snapshot.progress is None:
        raise ValueError("Agent restoration requires saved execution progress")
    if snapshot.progress.feature_state is None:
        raise ValueError("Checkpoint has no supported chat feature state")
    state = _FEATURE_STATE.validate_python(snapshot.progress.feature_state)
    context = checkpoint.agent_state
    token_counter = get_llm_token_counter(llm)
    if isinstance(state, ChatFeatureState):
        return ChatAgent(
            is_subagent=snapshot.parent_run_id is not None,
            messages=context.messages,
            tools=tools,
            code_mode=state.code_mode,
            custom_agent_prompt=state.custom_prompt,
            additional_context=state.request_context,
            base_system_prompt=state.base_prompt,
            context_files=state.context_files.restore(),
            persona=state.persona,
            user_memory_context=state.memory,
            llm=llm,
            token_counter=token_counter,
            preferred_tool_id=state.preferred_tool_id,
            user_identity=user_identity,
            reasoning_effort=state.reasoning_effort,
            include_citations=state.include_citations,
            all_injected_file_metadata=state.file_metadata,
            inject_memories_in_prompt=state.inject_memories,
            reminders_enabled=state.reminders_enabled,
            checkpoint=context.checkpoint,
            previous_run_id=snapshot.previous_run_id,
            agent_id=snapshot.agent_id,
            create_subagent=subagent_factory(depth + 1)
            if depth > 0
            or any(tool.name == ListAgentsTool.name for tool in snapshot.progress.tools)
            else None,
            can_spawn=depth < MAX_CHILD_DEPTH,
        )
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
        )
    return DeepResearchAgent(
        messages=context.messages,
        allowed_tools=tools,
        additional_context=state.request_context,
        context_files=state.context_files.restore() if state.context_files else None,
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
    )


def persist_checkpoint_files(
    checkpoint: ExecutionCheckpoint, *, session_id: UUID
) -> list[str]:
    """Replace transient file contents with tenant-scoped file-store references.

    Returns the file IDs of the parked programs' dumps that it saved, which
    only this checkpoint holds; a failed save deletes the dumps saved before it."""
    dumps: list[str] = []

    def save(file: SavedChatFile, *, unique: bool = False) -> str:
        """Save under a content ID, or a `unique` one for content that only
        this checkpoint owns; returns the file ID."""
        if file.file_id is not None:
            file.content = None
            return file.file_id
        if file.content is None:
            raise ValueError("Checkpoint file is missing its contents")
        name = uuid4().hex if unique else hashlib.sha256(file.content).hexdigest()
        file_id = f"{AGENT_CHECKPOINT_FILE_PREFIX}{session_id}/{name}"
        store = get_default_file_store()
        # Concurrent saves use identical bytes for this session-scoped content ID.
        if unique or not store.has_file(
            file_id, FileOrigin.OTHER, "application/octet-stream"
        ):
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
        return file_id

    def payload(value: BaseModel | None) -> None:
        if isinstance(value, StagedChatFiles):
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
            if progress.feature_state is not None:
                state = _FEATURE_STATE.validate_python(progress.feature_state)
                if isinstance(state, ChatFeatureState):
                    # Chat files, and each parked program's files for later
                    # calls and its dump, which each park makes anew.
                    for file in [
                        *state.chat_files,
                        *(
                            file
                            for cell in state.code_cells
                            for file in cell.staged_files
                        ),
                    ]:
                        save(file)
                    dumps.extend(
                        save(cell.program.dump, unique=True)
                        for cell in state.code_cells
                    )
                    progress.feature_state = _JSON_OBJECT.validate_python(
                        state.model_dump(mode="json")
                    )
            for answer in progress.human_tool_answers.values():
                if answer.result is not None:
                    payload(answer.result.details)
                    payload(answer.result.metadata)
        for child in record.child_runs:
            snapshot(child)

    try:
        messages(checkpoint.agent_state.messages)
        snapshot(checkpoint.run_state)
    except BaseException:
        delete_files_best_effort(dumps, CHECKPOINT_DUMP_CLEANUP)
        raise
    return dumps
