"""Persist agent conversations within chat branch and retention boundaries."""

from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, TypeAdapter
from sqlalchemy import Text, case, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, load_only, selectinload

from onyx.agents.coordination import AgentInfo
from onyx.agents.transcript import AgentConfiguration, AgentTranscript
from onyx.chat.models import (
    MAX_DISCOVERED_AGENTS,
    ChatExecutionRecord,
    MessagePresentation,
    RestoredAgent,
    ToolRecordReference,
)
from onyx.db.chat import translate_db_search_doc_to_saved_search_doc
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import AgentRun, ChatMessage, ChatSession, ChatSessionAgent
from onyx.utils.postgres_sanitization import sanitize_json_like

MAX_AGENT_HISTORY_RUNS = 512
MAX_AGENT_HISTORY_BYTES = 16 * 1024 * 1024
MAX_AGENT_DEPTH = 8

_JSON = TypeAdapter(dict[str, JsonValue])
_RELATION_FIELDS = {
    "agent_id",
    "agent_path",
    "agent_description",
    "restoration_config",
    "run_id",
    "previous_run_id",
    "parent_run_id",
    "parent_tool_call_id",
    "parent_message_id",
    "child_runs",
}


class ChatResponseRendering(BaseModel):
    presentation: list[MessagePresentation] = Field(default_factory=list)
    tool_records: list[ToolRecordReference] = Field(default_factory=list)


class _HistoryLink(BaseModel):
    id: int
    parent_message_id: int | None
    chat_session_id: UUID


def visible_message_ids(db_session: Session, message: ChatMessage) -> list[int]:
    """Return the selected ancestry, including the current response."""
    ancestry = (
        select(
            ChatMessage.id, ChatMessage.parent_message_id, ChatMessage.chat_session_id
        )
        .where(ChatMessage.id == message.id)
        .cte("agent_ancestry", recursive=True)
    )
    ancestry = ancestry.union(
        select(
            ChatMessage.id, ChatMessage.parent_message_id, ChatMessage.chat_session_id
        ).join(ancestry, ChatMessage.id == ancestry.c.parent_message_id)
    )
    rows = TypeAdapter(list[_HistoryLink]).validate_python(
        db_session.execute(select(ancestry)).mappings().all()
    )
    if any(row.chat_session_id != message.chat_session_id for row in rows):
        raise ValueError("Chat history crosses sessions")
    parents = {row.id: row.parent_message_id for row in rows}
    ids: list[int] = []
    current: int | None = message.id
    while current is not None:
        if current in ids:
            raise ValueError("Chat history contains a cycle")
        ids.append(current)
        current = parents[current]
    return ids


class AgentBranch(BaseModel):
    chat_session_id: UUID
    message_ids: list[int]


def load_agent_branch(message_id: int) -> AgentBranch:
    """Read response ancestry after the caller authorizes access."""
    with get_session_with_current_tenant() as db_session:
        message = db_session.get(
            ChatMessage,
            message_id,
            options=[load_only(ChatMessage.id, ChatMessage.chat_session_id)],
        )
        if message is None:
            raise ValueError("Chat response is unavailable")
        return AgentBranch(
            chat_session_id=message.chat_session_id,
            message_ids=visible_message_ids(db_session, message),
        )


def _agent_path(agent: ChatSessionAgent, agents: dict[str, ChatSessionAgent]) -> str:
    segments = [agent.name]
    visited = {agent.id}
    parent_id = agent.parent_agent_id
    while parent_id is not None:
        if parent_id in visited:
            raise ValueError("Agent registration contains a cycle")
        visited.add(parent_id)
        parent = agents[parent_id]
        segments.append(parent.name)
        parent_id = parent.parent_agent_id
    return "/" + "/".join(reversed(segments))


def _read_run(row: AgentRun, agents: dict[str, ChatSessionAgent]) -> AgentTranscript:
    transcript = AgentTranscript.model_validate(row.transcript)
    transcript.agent_id = row.agent_id
    transcript.agent_path = _agent_path(row.agent, agents)
    transcript.agent_description = row.agent.description
    transcript.restoration_config = (
        AgentConfiguration.model_validate(row.agent.restoration_config)
        if row.agent.restoration_config
        else None
    )
    transcript.run_id = row.id
    transcript.previous_run_id = row.previous_run_id
    transcript.parent_run_id = row.parent_run_id
    transcript.parent_tool_call_id = row.parent_tool_call_id
    transcript.parent_message_id = row.parent_message_id
    return transcript


def _root_run(message: ChatMessage) -> AgentRun:
    roots = [run for run in message.agent_runs if run.parent_run_id is None]
    if len(roots) != 1:
        raise ValueError("A saved chat response must contain exactly one root run")
    return roots[0]


def read_chat_execution(message: ChatMessage) -> ChatExecutionRecord | None:
    if message.response_rendering is None:
        return None
    presentation = ChatResponseRendering.model_validate(message.response_rendering)
    root = _root_run(message)
    agents = {row.agent_id: row.agent for row in message.agent_runs}
    runs = {row.id: _read_run(row, agents) for row in message.agent_runs}
    for row in message.agent_runs:
        if row.parent_run_id is not None:
            runs[row.parent_run_id].child_runs.append(runs[row.id])
    return ChatExecutionRecord(
        transcript=runs[root.id],
        presentation=presentation.presentation,
        tool_records=presentation.tool_records,
    )


def read_root_transcript(message: ChatMessage) -> AgentTranscript | None:
    if message.response_rendering is None:
        return None
    root = _root_run(message)
    return _read_run(root, {root.agent_id: root.agent})


def _indexed_runs(transcript: AgentTranscript) -> dict[str, AgentTranscript]:
    incoming: dict[str, AgentTranscript] = {}

    def collect(run: AgentTranscript) -> None:
        if run.agent_id is None or run.run_id is None or run.run_id in incoming:
            raise ValueError("Saved runs require distinct run IDs")
        incoming[run.run_id] = run
        for child in run.child_runs:
            collect(child)

    collect(transcript)
    return incoming


def set_agent_transcript(
    message: ChatMessage,
    transcript: AgentTranscript | None,
    *,
    db_session: Session,
    persist_content: bool,
    presentation: list[MessagePresentation] | None = None,
    tool_records: list[ToolRecordReference] | None = None,
) -> None:
    """Save terminal run records and presentation; the caller owns the transaction."""
    if not persist_content or transcript is None:
        message.response_rendering = None
        return
    incoming = _indexed_runs(transcript)
    payloads = {
        run_id: _JSON.validate_python(
            sanitize_json_like(run.model_dump(mode="json", exclude=_RELATION_FIELDS))
        )
        for run_id, run in incoming.items()
    }
    db_session.execute(
        select(ChatSession.id)
        .where(ChatSession.id == message.chat_session_id)
        .with_for_update()
    ).scalar_one()
    db_session.refresh(message, ["response_rendering"])
    if message.response_rendering is not None:
        raise ValueError("Chat response already has a saved execution")
    branch_ids = visible_message_ids(db_session, message)
    agent_ids = {run.agent_id for run in incoming.values()}
    agents = list(
        db_session.scalars(
            select(ChatSessionAgent).where(
                ChatSessionAgent.id.in_(agent_ids),
                ChatSessionAgent.chat_session_id == message.chat_session_id,
            )
        )
    )
    by_id = {agent.id: agent for agent in agents}
    predecessor_ids = {
        run.previous_run_id
        for run in incoming.values()
        if run.previous_run_id is not None and run.previous_run_id not in incoming
    }
    predecessors = {
        row.id: row
        for row in db_session.execute(
            select(AgentRun.id, AgentRun.agent_id, AgentRun.chat_message_id).where(
                AgentRun.id.in_(predecessor_ids)
            )
        )
    }

    accepted_runs: set[str] = set()

    def validate_history(run: AgentTranscript, parent_id: str | None) -> None:
        agent = by_id.get(run.agent_id)
        if agent is None:
            if parent_id is None:
                raise ValueError("Root identity must be reserved before execution")
            agent = ChatSessionAgent(
                id=run.agent_id,
                chat_session_id=message.chat_session_id,
                parent_agent_id=parent_id,
                creation_message_id=message.id,
                name=run.agent_path.rsplit("/", 1)[-1],
                description=run.agent_description,
                restoration_config=run.restoration_config.model_dump(mode="json")
                if run.restoration_config
                else {},
            )
            db_session.add(agent)
            db_session.flush()
            by_id[agent.id] = agent
        if (
            agent.parent_agent_id != parent_id
            or (
                agent.creation_message_id is not None
                and agent.creation_message_id not in branch_ids
            )
            or _agent_path(agent, by_id) != run.agent_path
        ):
            raise ValueError("Run agent is unavailable on the selected branch")
        if run.previous_run_id is not None:
            previous = incoming.get(run.previous_run_id)
            saved = predecessors.get(run.previous_run_id)
            if previous is not None:
                if (
                    previous.agent_id != run.agent_id
                    or run.previous_run_id not in accepted_runs
                ):
                    raise ValueError("Agent predecessor belongs to another agent")
            elif (
                saved is None
                or saved.agent_id != run.agent_id
                or saved.chat_message_id not in branch_ids
            ):
                raise ValueError(
                    "Agent predecessor is unavailable on the selected branch"
                )
        if run.run_id is None:
            raise ValueError("A saved run requires a run ID")
        accepted_runs.add(run.run_id)
        for child in run.child_runs:
            validate_history(child, agent.id)

    validate_history(transcript, None)
    next_run_index = 0

    def store(run: AgentTranscript, parent_run_id: str | None) -> str:
        nonlocal next_run_index
        if run.agent_id is None:
            raise ValueError("A saved run requires an agent ID")
        agent = by_id[run.agent_id]
        run_id = run.run_id
        if run_id is None:
            raise ValueError("A saved run requires a run ID")
        row = AgentRun(
            id=run_id,
            agent_id=agent.id,
            chat_message_id=message.id,
            previous_run_id=run.previous_run_id,
            parent_run_id=parent_run_id,
            parent_tool_call_id=run.parent_tool_call_id,
            parent_message_id=run.parent_message_id,
            run_index=next_run_index,
            transcript=payloads[run_id],
        )
        next_run_index += 1
        db_session.add(row)
        db_session.flush()
        for child in run.child_runs:
            store(child, run_id)
        return run_id

    store(transcript, None)
    message.response_rendering = ChatResponseRendering(
        presentation=presentation or [],
        tool_records=tool_records or [],
    ).model_dump(mode="json")
    db_session.expire(message, ["agent_runs"])


def get_or_create_root_agent(message_id: int, agent_id: str) -> str:
    """Commit a stable session identity after the caller authorizes the response."""
    with get_session_with_current_tenant() as db_session:
        message = db_session.get(ChatMessage, message_id)
        if message is None:
            raise ValueError("Chat response is unavailable")
        if not record_mode_persists_content(message.chat_session.incognito_record_mode):
            return agent_id
        statement = (
            insert(ChatSessionAgent)
            .values(
                id=agent_id,
                chat_session_id=message.chat_session_id,
                name="root",
                description="",
                restoration_config={},
            )
            .on_conflict_do_nothing(
                index_elements=[ChatSessionAgent.chat_session_id],
                index_where=ChatSessionAgent.parent_agent_id.is_(None),
            )
        )
        db_session.execute(statement)
        root_id = db_session.scalar(
            select(ChatSessionAgent.id).where(
                ChatSessionAgent.chat_session_id == message.chat_session_id,
                ChatSessionAgent.parent_agent_id.is_(None),
            )
        )
        if root_id is None:
            raise ValueError("Chat root identity is unavailable")
        db_session.commit()
        return root_id


def _agent_ancestors(
    db_session: Session, agent: ChatSessionAgent
) -> dict[str, ChatSessionAgent]:
    agents = {agent.id: agent}
    current = agent
    while current.parent_agent_id is not None:
        if len(agents) > MAX_AGENT_DEPTH or current.parent_agent_id in agents:
            raise ValueError(
                "Agent hierarchy contains a cycle or exceeds the depth limit"
            )
        parent = db_session.get(ChatSessionAgent, current.parent_agent_id)
        if parent is None or parent.chat_session_id != agent.chat_session_id:
            raise ValueError("Agent parent is unavailable")
        agents[parent.id] = parent
        current = parent
    return agents


def _visible_agent(
    db_session: Session, branch: AgentBranch, agent_id: str
) -> ChatSessionAgent:
    agent = db_session.get(ChatSessionAgent, agent_id)
    if (
        agent is None
        or agent.chat_session_id != branch.chat_session_id
        or (
            agent.creation_message_id is not None
            and agent.creation_message_id not in branch.message_ids
        )
    ):
        raise ValueError("Agent is unavailable on the selected branch")
    return agent


def _latest_run_id(
    db_session: Session, agent_id: str, message_ids: list[int]
) -> str | None:
    # Ancestry order captures branch placement even when ancestors finish later.
    return db_session.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.chat_message_id.in_(message_ids),
        )
        .order_by(
            case(
                {
                    message_id: position
                    for position, message_id in enumerate(message_ids)
                },
                value=AgentRun.chat_message_id,
            ),
            AgentRun.run_index.desc(),
        )
        .limit(1)
    )


def _load_history(
    db_session: Session, branch: AgentBranch, agent: ChatSessionAgent
) -> RestoredAgent:
    by_agent = _agent_ancestors(db_session, agent)
    head_id = _latest_run_id(db_session, agent.id, branch.message_ids)
    chain = (
        select(
            AgentRun.id,
            AgentRun.previous_run_id,
            func.octet_length(AgentRun.transcript.cast(Text)).label("size"),
            literal(0).label("depth"),
        )
        .where(AgentRun.id == head_id)
        .cte("agent_history", recursive=True)
    )
    chain = chain.union_all(
        select(
            AgentRun.id,
            AgentRun.previous_run_id,
            func.octet_length(AgentRun.transcript.cast(Text)),
            chain.c.depth + 1,
        )
        .join(chain, AgentRun.id == chain.c.previous_run_id)
        .where(
            AgentRun.agent_id == agent.id,
            AgentRun.chat_message_id.in_(branch.message_ids),
            chain.c.depth < MAX_AGENT_HISTORY_RUNS,
        )
    )
    links = db_session.execute(select(chain).order_by(chain.c.depth)).all()
    if len(links) > MAX_AGENT_HISTORY_RUNS or len({row.id for row in links}) != len(
        links
    ):
        raise ValueError("Agent history contains a cycle or exceeds the run limit")
    if links and links[-1].previous_run_id is not None:
        raise ValueError("Agent history is incomplete on the selected branch")
    if sum(row.size for row in links) > MAX_AGENT_HISTORY_BYTES:
        raise ValueError("Agent history exceeds the content limit")
    rows = {
        row.id: row
        for row in db_session.scalars(
            select(AgentRun).where(AgentRun.id.in_([link.id for link in links]))
        )
    }
    transcripts = [_read_run(rows[link.id], by_agent) for link in links]
    restored = RestoredAgent(
        agent_id=agent.id,
        parent_agent_id=agent.parent_agent_id,
        agent_path=_agent_path(agent, by_agent),
        description=agent.description,
        configuration=AgentConfiguration.model_validate(agent.restoration_config)
        if agent.restoration_config
        else None,
        transcripts=list(reversed(transcripts)),
    )
    if transcripts:
        run_ids = {run.run_id for run in transcripts}
        messages = (
            db_session.scalars(
                select(ChatMessage)
                .join(AgentRun, AgentRun.chat_message_id == ChatMessage.id)
                .where(
                    AgentRun.id.in_(run_ids),
                )
                .options(selectinload(ChatMessage.search_docs))
            )
            .unique()
            .all()
        )
        for message in messages:
            if message.response_rendering is None:
                continue
            presentation = ChatResponseRendering.model_validate(
                message.response_rendering
            )
            documents = {
                doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
                for doc in message.search_docs
            }
            for item in presentation.presentation:
                if item.run_id not in run_ids:
                    continue
                for number, document_id in item.citation_documents.items():
                    restored.sources[number] = documents[document_id]
    return restored


def load_agent_history(message_id: int, agent_id: str) -> RestoredAgent:
    """Load one authorized agent's selected conversation and source references."""
    branch = load_agent_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        return _load_history(
            db_session, branch, _visible_agent(db_session, branch, agent_id)
        )


def load_saved_run(
    message_id: int, run_id: str, parent_agent_id: str
) -> AgentTranscript | None:
    """Read one archived direct-child result without constructing an executable agent."""
    branch = load_agent_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        statement = (
            select(AgentRun)
            .join(ChatSessionAgent)
            .where(
                AgentRun.id == run_id,
                AgentRun.chat_message_id.in_(branch.message_ids),
                ChatSessionAgent.chat_session_id == branch.chat_session_id,
                ChatSessionAgent.parent_agent_id == parent_agent_id,
            )
        )
        size = db_session.scalar(
            statement.with_only_columns(
                func.octet_length(AgentRun.transcript.cast(Text))
            )
        )
        if size is None:
            return None
        if size > MAX_AGENT_HISTORY_BYTES:
            raise ValueError("Agent run exceeds the content limit")
        row = db_session.scalar(statement)
        if row is None:
            return None
        return _read_run(row, _agent_ancestors(db_session, row.agent))


def load_session_agent_metadata(message_id: int) -> list[AgentInfo]:
    """Read recent branch-visible identities and their ancestors for SDK discovery."""
    branch = load_agent_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        agents = list(
            db_session.scalars(
                select(ChatSessionAgent)
                .where(
                    ChatSessionAgent.chat_session_id == branch.chat_session_id,
                    (ChatSessionAgent.creation_message_id.is_(None))
                    | (ChatSessionAgent.creation_message_id.in_(branch.message_ids)),
                )
                .order_by(
                    ChatSessionAgent.creation_message_id.desc().nullsfirst(),
                    ChatSessionAgent.id,
                )
                .limit(MAX_DISCOVERED_AGENTS)
            )
        )
        by_id = {agent.id: agent for agent in agents}
        for agent in agents:
            by_id.update(_agent_ancestors(db_session, agent))
        return _agent_metadata(db_session, branch, by_id)


def _agent_metadata(
    db_session: Session, branch: AgentBranch, by_id: dict[str, ChatSessionAgent]
) -> list[AgentInfo]:
    positions = {
        message_id: position for position, message_id in enumerate(branch.message_ids)
    }
    ranked = (
        select(
            AgentRun.agent_id,
            AgentRun.id,
            AgentRun.transcript["status"].as_string().label("status"),
            func.row_number()
            .over(
                partition_by=AgentRun.agent_id,
                order_by=(
                    case(positions, value=AgentRun.chat_message_id),
                    AgentRun.run_index.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            AgentRun.agent_id.in_(by_id),
            AgentRun.chat_message_id.in_(branch.message_ids),
        )
        .subquery()
    )
    latest_by_agent = {
        row.agent_id: row
        for row in db_session.execute(select(ranked).where(ranked.c.position == 1))
    }
    return [
        AgentInfo(
            id=agent.id,
            path=_agent_path(agent, by_id),
            parent_id=agent.parent_agent_id,
            description=agent.description,
            restoration_config=AgentConfiguration.model_validate(
                agent.restoration_config
            )
            if agent.restoration_config
            else None,
            latest_run_id=latest_by_agent[agent.id].id
            if agent.id in latest_by_agent
            else None,
            status=latest_by_agent[agent.id].status
            if agent.id in latest_by_agent
            else None,
        )
        for agent in by_id.values()
    ]


def lookup_session_agent(
    message_id: int, agent_id: str, parent_agent_id: str
) -> AgentInfo | None:
    """Resolve one branch-visible child, including identities outside discovery's page."""
    branch = load_agent_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        if db_session.get(ChatSessionAgent, parent_agent_id) is None:
            return None
        parent = _visible_agent(db_session, branch, parent_agent_id)
        ancestors = _agent_ancestors(db_session, parent)
        agent = db_session.scalar(
            select(ChatSessionAgent).where(
                ChatSessionAgent.chat_session_id == branch.chat_session_id,
                ChatSessionAgent.parent_agent_id == parent_agent_id,
                ChatSessionAgent.id == agent_id,
                ChatSessionAgent.creation_message_id.in_(branch.message_ids),
            )
        )
        if agent is None:
            return None
        ancestors[agent.id] = agent
        return next(
            info
            for info in _agent_metadata(db_session, branch, ancestors)
            if info.id == agent.id
        )
