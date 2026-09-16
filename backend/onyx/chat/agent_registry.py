"""Bind branch-visible agent identities to current feature dependencies."""

from uuid import UUID

from onyx.agents.coordination import AgentCoordinator, AgentInfo
from onyx.agents.runtime import Agent
from onyx.agents.transcript import AgentTranscript
from onyx.chat.incognito_context import (
    get_or_create_incognito_root_id,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_saved_run,
    lookup_incognito_agent,
)
from onyx.chat.models import RestoredAgent
from onyx.db.agent_transcript import (
    get_or_create_root_agent,
    load_agent_branch,
    load_agent_history,
    load_saved_run,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.deep_research.research_agent import ResearchAgent, ResearchConfiguration
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.tools.interface import Tool


def _restore_agent(
    saved: RestoredAgent,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity,
) -> Agent:
    configuration = saved.configuration
    if configuration is None or configuration.feature != "research":
        raise ValueError("This agent's external resources are no longer available")
    settings = ResearchConfiguration.model_validate(configuration.settings)
    latest = saved.transcripts[-1] if saved.transcripts else None
    agent = ResearchAgent(
        messages=[
            message.model_copy(deep=True)
            for run in saved.transcripts
            for message in [*run.input_messages, *run.messages]
        ],
        checkpoint=latest.checkpoint if latest else None,
        previous_run_id=latest.run_id if latest else None,
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


def bind_chat_agents(
    root: Agent,
    *,
    message_id: int,
    previous_run_id: str | None,
    chat_session_id: UUID,
    persist_content: bool,
    llm: LLM,
    tools: list[Tool],
    user_identity: LLMUserIdentity,
) -> AgentCoordinator:
    """Bind agent restoration to the authorized request and selected branch."""
    branch = load_agent_branch(message_id)
    if branch.chat_session_id != chat_session_id:
        raise ValueError("Response belongs to another chat session")
    if persist_content:
        root.id = get_or_create_root_agent(message_id, root.id)
        saved_agents = load_session_agent_metadata(message_id)
    else:
        root.id = get_or_create_incognito_root_id(chat_session_id, root.id)
        saved_agents = load_incognito_agent_metadata(
            chat_session_id, branch.message_ids
        )

    def lookup_agent(agent_id: str, parent_id: str) -> AgentInfo | None:
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
        history = (
            load_agent_history(message_id, saved.id)
            if persist_content
            else load_incognito_agent_history(
                chat_session_id, branch.message_ids, saved.id
            )
        )
        return _restore_agent(history, llm, tools, user_identity)

    def read_run(run_id: str, parent_id: str) -> AgentTranscript | None:
        if persist_content:
            return load_saved_run(message_id, run_id, parent_id)
        return load_incognito_saved_run(
            chat_session_id, branch.message_ids, run_id, parent_id
        )

    coordinator = AgentCoordinator(
        agents=saved_agents,
        lookup_agent=lookup_agent,
        resolve_agent=resolve_agent,
        read_run=read_run,
    )
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
