"""Restore subagents from the selected chat branch with current tools and LLM settings."""

from collections.abc import Callable, Collection

from onyx.agents.agent_coordination import AgentDirectory
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    RunState,
    RunStatus,
)
from onyx.agents.runtime import Agent
from onyx.chat.history_store import ChatHistoryStore
from onyx.chat.models import SavedAgentContext
from onyx.chat.response import response_snapshot
from onyx.chat.run_store import ChatRunStore
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)


class ChatAgentDirectory(AgentDirectory):
    """Resolve children and saved runs within one authorized chat branch."""

    def __init__(
        self,
        *,
        history_store: ChatHistoryStore,
        store: ChatRunStore | None,
        build_agent: Callable[[SavedAgentContext], Agent],
    ) -> None:
        self.history_store = history_store
        self.store = store
        self.build_agent = build_agent
        self.tenant_id = (
            store.tenant_id if store is not None else get_current_tenant_id()
        )

    def list_agents(self) -> list[AgentInfo]:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            agents = self.history_store.list_agents()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        if self.store is not None:
            pending: dict[str, list[AgentMessageReceipt]] = {}
            for receipt in self.store.pending_messages():
                pending.setdefault(receipt.agent_id, []).append(receipt)
            agents = [
                agent.model_copy(update={"pending_messages": pending.get(agent.id, [])})
                for agent in agents
            ]
        return agents

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            agent = self.history_store.lookup_agent(agent_id, parent_id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        if agent is not None and self.store is not None:
            agent = agent.model_copy(
                update={"pending_messages": self.store.pending_messages(agent_id)}
            )
        return agent

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent:
        saved = self.lookup_agent(agent_id, parent_id)
        if saved is None:
            raise ValueError("Agent is not a visible child of this parent")
        if (
            self.store is not None
            and saved.latest_run_id is not None
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

    def completed_agents(
        self,
        parent_id: str,
        received_run_ids: Collection[str],
        *,
        limit: int,
    ) -> list[AgentCompletion]:
        if self.store is None:
            return []
        return self.store.completed_agents(parent_id, received_run_ids, limit=limit)

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        if self.store is not None:
            return self.store.read_run(run_id, parent_id)
        record = self.history_store.load_saved_run(run_id, parent_id)
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

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        if self.lookup_agent(request.agent_id, request.parent_id) is None:
            raise ValueError("Agent is unavailable to this parent")
        if self.store is None:
            raise ValueError("Agent messages require durable execution ownership")
        return self.store.submit_message(request)

    def cancel_message(self, agent_id: str, parent_id: str, message_id: str) -> bool:
        if self.lookup_agent(agent_id, parent_id) is None:
            raise ValueError("Agent is unavailable to this parent")
        if self.store is None:
            raise ValueError("Agent messages require durable execution ownership")
        return self.store.cancel_message(agent_id, message_id)
