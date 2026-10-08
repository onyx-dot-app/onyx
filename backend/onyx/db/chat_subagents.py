"""Select child sessions and restore their branch-visible conversation context."""

from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import Text, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session, aliased, joinedload, load_only, selectinload
from sqlalchemy.sql.selectable import CTE

from onyx.agents.execution_records import RunStatus, run_input_message_id
from onyx.agents.models import AgentInfo, messages_from_steps
from onyx.chat.models import (
    MAX_DISCOVERED_AGENTS,
    MessageRendering,
    ResponseRecord,
    SavedAgentContext,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    SessionAncestor,
    agent_path_from_ancestors,
    agent_session_path,
    checkpoint_from_summary,
    find_summary_for_ancestry,
    parent_session_id,
    session_ancestors,
    translate_db_search_doc_to_saved_search_doc,
    visible_message_ids,
)
from onyx.db.chat_response import (
    read_response_record,
    read_response_steps,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage, ChatResponseMessage, ChatSession, ToolCall
from onyx.llm.models import Message, UserMessage

MAX_AGENT_HISTORY_BYTES = 16 * 1024 * 1024


class ChatBranch(BaseModel):
    chat_session_id: UUID
    message_ids: list[int]


def load_chat_branch(message_id: int) -> ChatBranch:
    """Read response ancestry after the caller authorizes access."""
    with get_session_with_current_tenant() as db_session:
        message = db_session.get(
            ChatMessage,
            message_id,
            options=[
                load_only(ChatMessage.id, ChatMessage.chat_session_id),
                joinedload(ChatMessage.chat_session).load_only(
                    ChatSession.spawned_by_message_id, ChatSession.deleted
                ),
            ],
        )
        if (
            message is None
            or message.chat_session.spawned_by_message_id is not None
            or message.chat_session.deleted
        ):
            raise ValueError("Chat response is unavailable")
        return ChatBranch(
            chat_session_id=message.chat_session_id,
            message_ids=visible_message_ids(db_session, message),
        )


def _visible_agent(
    db_session: Session, branch: ChatBranch, agent_id: str
) -> ChatSession:
    responses = _selected_responses(branch)
    agent = db_session.scalar(
        select(ChatSession).where(
            ChatSession.id == UUID(agent_id),
            or_(
                ChatSession.id == branch.chat_session_id,
                ChatSession.spawned_by_message_id.in_(select(responses.c.id)),
            ),
        )
    )
    if agent is None:
        raise ValueError("Agent is unavailable on the selected branch")
    return agent


class _ResponseLink(BaseModel):
    id: int
    chat_session_id: UUID
    previous_response_id: int | None
    root_id: int
    status: RunStatus


def _selected_responses(branch: ChatBranch) -> CTE:
    """Follow branch-visible invocations without loading response payloads."""
    question = aliased(ChatMessage)
    previous = aliased(ChatMessage)
    responses = (
        select(
            ChatMessage.id,
            ChatMessage.chat_session_id,
            case(
                (previous.response_status.is_not(None), question.parent_message_id),
                else_=None,
            ).label("previous_response_id"),
            ChatMessage.id.label("root_id"),
            ChatMessage.response_status.label("status"),
            literal(0).label("depth"),
        )
        .join(question, ChatMessage.parent_message_id == question.id)
        .outerjoin(previous, question.parent_message_id == previous.id)
        .where(
            ChatMessage.id.in_(branch.message_ids),
            ChatMessage.chat_session_id == branch.chat_session_id,
            ChatMessage.response_status.is_not(None),
        )
        .cte("selected_responses", recursive=True)
    )
    responses = responses.union_all(
        select(
            ChatMessage.id,
            ChatMessage.chat_session_id,
            question.parent_message_id,
            responses.c.root_id,
            ChatMessage.response_status,
            responses.c.depth + 1,
        )
        .select_from(responses)
        .join(ToolCall, ToolCall.parent_chat_message_id == responses.c.id)
        .join(question, question.invoking_tool_call_id == ToolCall.id)
        .join(ChatMessage, ChatMessage.parent_message_id == question.id)
        .where(
            ChatMessage.response_status.is_not(None),
            responses.c.depth < MAX_AGENT_DEPTH,
        )
    )
    return responses


def _selected_response_links(
    db_session: Session, branch: ChatBranch, agent_ids: list[UUID]
) -> dict[UUID, list[_ResponseLink]]:
    """Read branch-visible response links once, then order each conversation."""
    if not agent_ids:
        return {}
    responses = _selected_responses(branch)
    rows = (
        db_session.execute(
            select(responses)
            .where(responses.c.chat_session_id.in_(agent_ids))
            .order_by(
                case(
                    {
                        message_id: index
                        for index, message_id in enumerate(branch.message_ids)
                    },
                    value=responses.c.root_id,
                ),
            )
            .limit(MAX_AGENT_HISTORY_RUNS * len(agent_ids) + 1)
        )
        .mappings()
        .all()
    )
    links_by_agent: dict[UUID, list[_ResponseLink]] = {
        agent_id: [] for agent_id in agent_ids
    }
    for link in TypeAdapter(list[_ResponseLink]).validate_python(rows):
        links = links_by_agent[link.chat_session_id]
        links.append(link)
        if len(links) > MAX_AGENT_HISTORY_RUNS:
            raise ValueError("Selected agent history exceeds its response limit")
    return {
        agent_id: links
        if agent_id == branch.chat_session_id
        else _order_response_links(links)
        for agent_id, links in links_by_agent.items()
    }


def _order_response_links(links: list[_ResponseLink]) -> list[_ResponseLink]:
    """Follow predecessors from the unique selected tip, newest response first."""
    if not links:
        return []
    predecessors = {link.previous_response_id for link in links}
    tips = [link for link in links if link.id not in predecessors]
    if len(tips) != 1:
        raise ValueError("Child history has ambiguous response selection")
    by_id = {link.id: link for link in links}
    selected: list[_ResponseLink] = []
    visited: set[int] = set()
    current = tips[0]
    while True:
        if current.id in visited:
            raise ValueError("Agent history contains a cycle")
        visited.add(current.id)
        selected.append(current)
        if current.previous_response_id is None:
            break
        predecessor = by_id.get(current.previous_response_id)
        if predecessor is None:
            raise ValueError("Child history crosses the selected branch")
        current = predecessor
    if len(selected) != len(links):
        raise ValueError("Child history contains disconnected responses")
    return selected


def _check_history_size(db_session: Session, response_ids: list[int]) -> None:
    item_bytes = (
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(
                        func.octet_length(cast(ChatResponseMessage.content, Text)), 0
                    )
                    + func.coalesce(
                        func.octet_length(cast(ChatResponseMessage.rendering, Text)), 0
                    )
                ),
                0,
            )
        )
        .where(ChatResponseMessage.chat_message_id.in_(response_ids))
        .scalar_subquery()
    )
    tool_bytes = (
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(func.octet_length(cast(ToolCall.result, Text)), 0)
                    + func.coalesce(
                        func.octet_length(cast(ToolCall.tool_call_arguments, Text)), 0
                    )
                ),
                0,
            )
        )
        .where(ToolCall.parent_chat_message_id.in_(response_ids))
        .scalar_subquery()
    )
    question = aliased(ChatMessage)
    input_bytes = (
        select(func.coalesce(func.sum(func.octet_length(question.message)), 0))
        .select_from(ChatMessage)
        .join(question, ChatMessage.parent_message_id == question.id)
        .where(ChatMessage.id.in_(response_ids))
        .scalar_subquery()
    )
    total_bytes = db_session.execute(
        select(item_bytes + tool_bytes + input_bytes)
    ).scalar_one()
    if total_bytes > MAX_AGENT_HISTORY_BYTES:
        raise ValueError("Agent history exceeds its content limit")


def _load_history(
    db_session: Session, branch: ChatBranch, agent: ChatSession
) -> SavedAgentContext:
    links = _selected_response_links(db_session, branch, [agent.id])[agent.id]
    by_id = {link.id: link for link in links}
    response_ids = [link.id for link in links]
    _check_history_size(db_session, response_ids)
    rows = {
        row.id: row
        for row in db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.id.in_(response_ids))
            .options(
                joinedload(ChatMessage.parent_message),
                selectinload(ChatMessage.response_messages),
                selectinload(ChatMessage.tool_calls),
            )
        )
    }
    responses = [rows[link.id] for link in links]
    messages: list[Message] = []
    for response in reversed(responses):
        question = response.parent_message
        if question is None or question.message_type != MessageType.USER:
            raise ValueError("Child response has no user instruction")
        if response.run_id is None:
            raise ValueError("Child response has no run identity")
        messages.append(
            UserMessage(
                id=run_input_message_id(response.run_id, 0), content=question.message
            )
        )
        messages.extend(messages_from_steps(read_response_steps(response)))
    restored = SavedAgentContext(
        agent_id=str(agent.id),
        configuration=agent.restoration_config,
        messages=messages,
        previous_run_id=str(responses[0].id) if responses else None,
    )
    if responses:
        summary = find_summary_for_ancestry(
            db_session, agent.id, visible_message_ids(db_session, responses[0])
        )
        restored.checkpoint = checkpoint_from_summary(summary)
    roots = {
        root.id: {
            doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
            for doc in root.search_docs
        }
        for root in db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.id.in_({link.root_id for link in links}))
            .options(selectinload(ChatMessage.search_docs))
        )
    }
    for response in reversed(responses):
        root_id = by_id[response.id].root_id
        documents = roots.get(root_id)
        if documents is None:
            raise ValueError("Root response is unavailable")
        for item in response.response_messages:
            if item.rendering:
                rendering = MessageRendering.model_validate(item.rendering)
                for number, document_id in rendering.citation_documents.items():
                    restored.sources[number] = documents[document_id]
    return restored


def load_agent_history(message_id: int, agent_id: str) -> SavedAgentContext:
    branch = load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        return _load_history(
            db_session, branch, _visible_agent(db_session, branch, agent_id)
        )


def load_saved_run(
    message_id: int, run_id: str, parent_agent_id: str
) -> ResponseRecord | None:
    """Read a completed child response after authorizing its parent branch."""
    branch = load_chat_branch(message_id)
    if not run_id.isdecimal():
        return None
    with get_session_with_current_tenant() as db_session:
        session_id = db_session.scalar(
            select(ChatMessage.chat_session_id).where(
                ChatMessage.id == int(run_id), ChatMessage.response_status.is_not(None)
            )
        )
        if session_id is None:
            return None
        agent = _visible_agent(db_session, branch, str(session_id))
        if parent_session_id(db_session, agent) != UUID(parent_agent_id):
            return None
        links = _selected_response_links(db_session, branch, [agent.id])[agent.id]
        if not any(link.id == int(run_id) for link in links):
            return None
        _check_history_size(db_session, [int(run_id)])
        response = db_session.scalar(
            select(ChatMessage)
            .where(ChatMessage.id == int(run_id))
            .options(
                selectinload(ChatMessage.response_messages),
                selectinload(ChatMessage.tool_calls),
                joinedload(ChatMessage.parent_message).joinedload(
                    ChatMessage.parent_message
                ),
            )
        )
        if response is None:
            return None
        record = read_response_record(response, agent_session_path(db_session, agent))
        summary = find_summary_for_ancestry(
            db_session, agent.id, visible_message_ids(db_session, response)
        )
        record.checkpoint = checkpoint_from_summary(summary)
        return record


def _agent_metadata(
    agent: ChatSession,
    ancestors: dict[UUID, SessionAncestor],
    links: list[_ResponseLink],
) -> AgentInfo:
    latest = links[0] if links else None
    parent_id = ancestors[agent.id].parent_id
    return AgentInfo(
        id=str(agent.id),
        path=agent_path_from_ancestors(agent.id, ancestors),
        parent_id=str(parent_id) if parent_id else None,
        description=agent.description or "" if parent_id else "",
        restoration_config=agent.restoration_config,
        latest_run_id=str(latest.id) if latest else None,
        status=latest.status if latest else None,
    )


def load_session_agent_metadata(
    message_id: int, *, branch: ChatBranch | None = None, include_root: bool = True
) -> list[AgentInfo]:
    branch = branch if branch is not None else load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        responses = _selected_responses(branch)
        agents = list(
            db_session.scalars(
                select(ChatSession)
                .where(
                    or_(
                        (ChatSession.id == branch.chat_session_id)
                        if include_root
                        else False,
                        ChatSession.spawned_by_message_id.in_(select(responses.c.id)),
                    )
                )
                .order_by(
                    ChatSession.spawned_by_message_id.desc().nullsfirst(),
                    ChatSession.id,
                )
                .limit(MAX_DISCOVERED_AGENTS)
            )
        )
        if not agents:
            return []
        agent_ids = [agent.id for agent in agents]
        ancestors = (
            session_ancestors(db_session, agent_ids)
            if any(agent.spawned_by_message_id is not None for agent in agents)
            else {
                agent.id: SessionAncestor(
                    id=agent.id, agent_name=agent.agent_name, parent_id=None
                )
                for agent in agents
            }
        )
        links = _selected_response_links(db_session, branch, agent_ids)
        return [_agent_metadata(agent, ancestors, links[agent.id]) for agent in agents]


def lookup_session_agent(
    message_id: int, agent_id: str, parent_agent_id: str
) -> AgentInfo | None:
    branch = load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        parent = _visible_agent(db_session, branch, parent_agent_id)
        responses = _selected_responses(branch)
        agent = db_session.scalar(
            select(ChatSession)
            .join(ChatMessage, ChatMessage.id == ChatSession.spawned_by_message_id)
            .where(
                ChatMessage.chat_session_id == parent.id,
                ChatSession.id == UUID(agent_id),
                ChatSession.spawned_by_message_id.in_(select(responses.c.id)),
            )
        )
        if agent is None:
            return None
        return _agent_metadata(
            agent,
            session_ancestors(db_session, [agent.id]),
            _selected_response_links(db_session, branch, [agent.id])[agent.id],
        )
