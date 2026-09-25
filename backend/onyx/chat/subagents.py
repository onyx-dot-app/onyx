"""Restore subagents from the selected chat branch with current tools and LLM settings."""

from collections.abc import Callable
from uuid import UUID

from onyx.agents.coordination import (
    AgentCoordinator,
    AgentDirectory,
    AgentInfo,
    RunStore,
)
from onyx.agents.models import RunState
from onyx.agents.runtime import Agent
from onyx.agents.transcript import RunStatus
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.incognito_context import (
    get_or_create_incognito_root_id,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_saved_run,
    lookup_incognito_agent,
)
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
from onyx.deep_research.research_agent import ResearchAgent
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.tools.interface import Tool
from shared_configs.contextvars import get_current_tenant_id


class ChatAgentDirectory(AgentDirectory):
    """Resolve children and saved runs within one authorized chat branch."""

    def __init__(
        self,
        *,
        message_id: int,
        chat_session_id: UUID,
        visible_message_ids: list[int],
        persist_content: bool,
        llm: LLM,
        tools: list[Tool],
        user_identity: LLMUserIdentity,
        store: ChatRunStore | None,
    ) -> None:
        self.message_id = message_id
        self.chat_session_id = chat_session_id
        self.visible_message_ids = visible_message_ids
        self.persist_content = persist_content
        self.llm = llm
        self.tools = tools
        self.user_identity = user_identity
        self.store = store

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        if self.store is not None:
            return self.store.lookup_agent(agent_id, parent_id)
        if self.persist_content:
            return lookup_session_agent(self.message_id, agent_id, parent_id)
        return lookup_incognito_agent(
            self.chat_session_id, self.visible_message_ids, agent_id, parent_id
        )

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent:
        saved = self.lookup_agent(agent_id, parent_id)
        if saved is None:
            raise ValueError("Agent is not a visible child of this parent")
        if self.store is not None and saved.latest_run_id is not None:
            history = self.store.load_history(saved.latest_run_id, parent_id)
        elif self.persist_content:
            history = load_agent_history(self.message_id, saved.id)
        else:
            history = load_incognito_agent_history(
                self.chat_session_id, self.visible_message_ids, saved.id
            )
        configuration = history.configuration
        if configuration is None:
            raise ValueError("This agent's external resources are no longer available")
        agent = ResearchAgent(
            messages=history.messages,
            checkpoint=history.checkpoint,
            previous_run_id=history.previous_run_id,
            sources=history.sources,
            tools=self.tools,
            llm=self.llm,
            token_counter=get_llm_token_counter(self.llm),
            user_identity=self.user_identity,
            language_section=configuration.language_section,
            reasoning_effort=configuration.reasoning_effort,
        ).agent
        agent.id = history.agent_id
        return agent

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        if self.store is not None:
            return self.store.read_run(run_id, parent_id)
        record = (
            load_saved_run(self.message_id, run_id, parent_id)
            if self.persist_content
            else load_incognito_saved_run(
                self.chat_session_id, self.visible_message_ids, run_id, parent_id
            )
        )
        return response_snapshot(record) if record is not None else None

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        if self.store is not None:
            return self.store.read_run_status(run_id, parent_id)
        record = self.read_run(run_id, parent_id)
        if record is None:
            raise ValueError("Response is unavailable on this branch")
        return record.status

    def cancel_run(self, run_id: str, parent_id: str) -> None:
        if self.store is not None:
            self.store.cancel_run(run_id, parent_id)
            return
        if not self.read_run_status(run_id, parent_id).is_terminal:
            raise ValueError("Remote cancellation requires durable execution ownership")


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
    response_store: RunStore | None = None,
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
            root_response=response_store,
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

    directory = ChatAgentDirectory(
        message_id=message_id,
        chat_session_id=chat_session_id,
        visible_message_ids=branch.message_ids,
        persist_content=persist_content,
        llm=llm,
        tools=tools,
        user_identity=user_identity,
        store=durable,
    )
    coordinator = (
        owner if owner is not None and durable is not None else AgentCoordinator()
    )
    if durable is not None:
        coordinator = durable.bind(
            coordinator,
            build_agent=lambda checkpoint: restore_chat_agent(
                checkpoint, llm=llm, tools=tools, user_identity=user_identity
            ),
            directory=directory,
        )
    else:
        coordinator = coordinator.view(directory=directory, store=response_store)
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
