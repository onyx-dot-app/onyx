"""Restore subagents from the selected chat branch with current tools and LLM settings."""

from collections.abc import Callable
from uuid import UUID

from onyx.agents.coordination import AgentCoordinator, AgentInfo
from onyx.agents.models import RunSnapshot
from onyx.agents.runtime import Agent
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.incognito_context import (
    get_or_create_incognito_root_id,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_saved_run,
    lookup_incognito_agent,
)
from onyx.chat.models import SavedAgentContext
from onyx.chat.response import response_snapshot
from onyx.chat.restoration import restore_chat_agent
from onyx.chat.run_store import ENABLE_CHAT_CHECKPOINTS, ChatRunStore
from onyx.db.chat_subagents import (
    load_agent_history,
    load_chat_branch,
    load_saved_run,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.deep_research.research_agent import ResearchAgent, ResearchConfiguration
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.tools.interface import Tool
from shared_configs.contextvars import get_current_tenant_id


def _restore_agent(
    saved: SavedAgentContext,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity,
) -> Agent:
    configuration = saved.configuration
    if configuration is None or configuration.feature != "research":
        raise ValueError("This agent's external resources are no longer available")
    settings = ResearchConfiguration.model_validate(configuration.settings)
    agent = ResearchAgent(
        messages=saved.messages,
        checkpoint=saved.checkpoint,
        previous_run_id=saved.previous_run_id,
        sources=saved.sources,
        tools=tools,
        llm=llm,
        token_counter=get_llm_token_counter(llm),
        user_identity=user_identity,
        language_section=settings.language_section,
        reasoning_effort=settings.reasoning_effort,
    ).agent
    agent.id = saved.agent_id
    return agent


def create_chat_agent_coordinator(
    root: Agent,
    *,
    message_id: int,
    previous_run_id: str | None,
    chat_session_id: UUID,
    persist_content: bool,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity,
    owner: AgentCoordinator | None = None,
    register_store: Callable[[ChatRunStore], None] | None = None,
    on_root_complete: Callable[[RunSnapshot], None] | None = None,
    control_cache: CacheBackend | None = None,
) -> AgentCoordinator:
    """Create a coordinator that can discover and restore subagents on this chat branch."""
    branch = load_chat_branch(message_id)
    if branch.chat_session_id != chat_session_id:
        raise ValueError("Response belongs to another chat session")
    durable = (
        ChatRunStore(
            tenant_id=get_current_tenant_id(),
            chat_session_id=chat_session_id,
            response_id=message_id,
            visible_response_ids=branch.message_ids,
            cache=get_cache_backend(),
            on_root_complete=on_root_complete,
            control_cache=control_cache,
        )
        if persist_content and ENABLE_CHAT_CHECKPOINTS
        else None
    )
    if durable is not None and register_store is not None:
        register_store(durable)
    root.id = str(chat_session_id)
    if persist_content:
        saved_agents = load_session_agent_metadata(message_id)
    else:
        root.id = get_or_create_incognito_root_id(chat_session_id, root.id)
        saved_agents = load_incognito_agent_metadata(
            chat_session_id, branch.message_ids
        )

    def lookup_agent(agent_id: str, parent_id: str) -> AgentInfo | None:
        if durable is not None:
            return durable.lookup_agent(agent_id, parent_id)
        return (
            lookup_session_agent(message_id, agent_id, parent_id)
            if persist_content
            else lookup_incognito_agent(
                chat_session_id, branch.message_ids, agent_id, parent_id
            )
        )

    def resolve_agent(agent_id: str, parent_id: str) -> Agent:
        saved = lookup_agent(agent_id, parent_id)
        if saved is None:
            raise ValueError("Agent is not a visible child of this parent")
        if durable is not None and saved.latest_run_id is not None:
            history = durable.load_history(saved.latest_run_id, parent_id)
            return _restore_agent(history, llm, tools, user_identity)
        history = (
            load_agent_history(message_id, saved.id)
            if persist_content
            else load_incognito_agent_history(
                chat_session_id, branch.message_ids, saved.id
            )
        )
        return _restore_agent(history, llm, tools, user_identity)

    def read_run(run_id: str, parent_id: str) -> RunSnapshot | None:
        if persist_content:
            record = load_saved_run(message_id, run_id, parent_id)
        else:
            record = load_incognito_saved_run(
                chat_session_id, branch.message_ids, run_id, parent_id
            )
        return response_snapshot(record) if record is not None else None

    coordinator = (
        owner if owner is not None and durable is not None else AgentCoordinator()
    )
    if durable is not None:
        coordinator = durable.bind(
            coordinator,
            build_agent=lambda checkpoint: restore_chat_agent(
                checkpoint, llm=llm, tools=tools, user_identity=user_identity
            ),
            resolve_agent=resolve_agent,
        )
    else:
        coordinator = coordinator.view(
            lookup_agent=lookup_agent,
            resolve_agent=resolve_agent,
            read_run=read_run,
        )
    for info in saved_agents:
        coordinator.register(info)
    coordinator.register(
        AgentInfo(
            id=root.id,
            path="/root",
            parent_id=None,
            description="",
            restoration_config=None,
            latest_run_id=previous_run_id,
        )
    )
    return coordinator
