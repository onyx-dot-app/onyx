"""Restore subagents from the selected chat branch with current tools and LLM settings."""

from collections.abc import Callable, Collection, Sequence

from onyx.agents.agent_coordination import AgentDirectory
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    BackgroundDelegation,
    RunState,
    RunStatus,
)
from onyx.agents.runtime import Agent
from onyx.chat.history_store import ChatHistoryStore
from onyx.chat.models import SavedAgentContext
from onyx.chat.run_store import ChatRunStore
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


class ChatAgentDirectory(AgentDirectory):
    """Resolve children and saved runs within one authorized chat branch."""

    def __init__(
        self,
        *,
        history_store: ChatHistoryStore,
        store: ChatRunStore,
        build_agent: Callable[[SavedAgentContext], Agent],
    ) -> None:
        self.history_store = history_store
        self.store = store
        self.build_agent = build_agent
        self.tenant_id = store.tenant_id

    def list_agents(self) -> list[AgentInfo]:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            agents = self.history_store.list_agents()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        pending = self.store.pending_message_counts()
        return [
            agent.model_copy(update={"pending_message_count": pending.get(agent.id, 0)})
            for agent in agents
        ]

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            agent = self.history_store.lookup_agent(agent_id, parent_id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        if agent is not None:
            agent = agent.model_copy(
                update={
                    "pending_message_count": self.store.pending_message_counts(
                        agent_id
                    ).get(agent_id, 0)
                }
            )
        return agent

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent:
        saved = self.lookup_agent(agent_id, parent_id)
        if saved is None:
            raise ValueError("Agent is not a visible child of this parent")
        if (
            saved.latest_run_id is not None
            and not self.store.read_run_status(
                saved.latest_run_id, parent_id
            ).is_terminal
        ):
            raise ValueError("Response must finish before another run starts")
        # Restoration must use the conversation's tenant, not the worker's context.
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            history = self.history_store.load_agent_history(saved.id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        return self.build_agent(history)

    def resolve_delegation_messages(
        self, parent_run_id: str, delegations: Sequence[BackgroundDelegation]
    ) -> dict[str, str | None]:
        return self.store.resolve_delegation_messages(parent_run_id, delegations)

    def completed_agents(
        self,
        parent_id: str,
        received_run_ids: Collection[str],
        *,
        limit: int,
    ) -> list[AgentCompletion]:
        return self.store.completed_agents(parent_id, received_run_ids, limit=limit)

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        return self.store.read_run(run_id, parent_id)

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        return self.store.read_run_status(run_id, parent_id)

    def cancel_run(self, run_id: str, parent_id: str) -> None:
        self.store.cancel_run(run_id, parent_id)

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        if self.lookup_agent(request.agent_id, request.parent_id) is None:
            raise ValueError("Agent is unavailable to this parent")
        return self.store.submit_message(request)
