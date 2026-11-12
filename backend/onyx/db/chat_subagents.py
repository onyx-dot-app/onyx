"""Select child sessions and restore their branch-visible conversation context."""

from collections.abc import Callable, Collection
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import (
    Text,
    and_,
    case,
    cast,
    func,
    or_,
    select,
)
from sqlalchemy.orm import (
    Session,
    aliased,
    joinedload,
    load_only,
    selectinload,
)
from sqlalchemy.sql.selectable import CTE

from onyx.agents.execution_records import run_input_message_id
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    RunStatus,
    messages_from_steps,
)
from onyx.chat.models import (
    MAX_DISCOVERED_AGENTS,
    ChatBranch,
    ChatMessageMetadata,
    MessageRendering,
    ResponseLink,
    SavedAgentContext,
    SessionAncestor,
)
from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import (
    MAX_AGENT_HISTORY_RUNS,
    agent_path_from_ancestors,
    checkpoint_from_summary,
    find_summary_for_ancestry,
    root_response_id,
    session_ancestors,
    translate_db_search_doc_to_saved_search_doc,
    visible_message_ids,
)
from onyx.db.chat_response import (
    read_response_steps,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatResponseItem,
    ChatSession,
    ToolCall,
)
from onyx.db.models import (
    SearchDoc as StoredSearchDoc,
)
from onyx.llm.models import Message, UserMessage

MAX_AGENT_HISTORY_BYTES = 16 * 1024 * 1024


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


def visible_agent(
    db_session: Session, branch: ChatBranch, agent_id: str
) -> ChatSession:
    responses = selected_responses(branch)
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


def selected_responses(branch: ChatBranch) -> CTE:
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
    # Every child question, including a follow-up, records its invocation.
    # Messages between agents chain runs beyond the spawn depth; each run is
    # newer than the run that started it, so the walk ends.
    invoked = responses.union_all(
        select(
            ChatMessage.id,
            ChatMessage.chat_session_id,
            question.parent_message_id,
            responses.c.root_id,
            ChatMessage.response_status,
        )
        .select_from(responses)
        .join(ToolCall, ToolCall.parent_chat_message_id == responses.c.id)
        .join(question, question.invoking_tool_call_id == ToolCall.id)
        .join(ChatMessage, ChatMessage.parent_message_id == question.id)
        .where(
            ChatMessage.response_status.is_not(None),
            ChatMessage.id > responses.c.id,
        )
    )
    # A run can continue history from another turn than its sender's, so it is
    # visible only when its previous run is visible too.
    connected = (
        select(invoked)
        .where(
            or_(
                invoked.c.chat_session_id == branch.chat_session_id,
                invoked.c.previous_response_id.is_(None),
            )
        )
        .cte("connected_responses", recursive=True)
    )
    return connected.union_all(
        select(invoked)
        .join(connected, invoked.c.previous_response_id == connected.c.id)
        .where(invoked.c.chat_session_id != branch.chat_session_id)
    )


def unfinished_agent_response_ids(db_session: Session, branch: ChatBranch) -> list[int]:
    """The branch's running or suspended agent runs, without the root's runs.

    A suspended run waits for its children and resumes when they finish.
    """
    selected = selected_responses(branch)
    return list(
        db_session.scalars(
            select(selected.c.id).where(
                selected.c.chat_session_id != branch.chat_session_id,
                selected.c.status.in_((RunStatus.RUNNING, RunStatus.SUSPENDED)),
            )
        )
    )


def latest_agent_responses(
    db_session: Session, branch: ChatBranch, agent_ids: Collection[str]
) -> dict[str, ChatMessage]:
    """Each agent's newest branch-visible response with a status."""
    if not agent_ids:
        return {}
    selected = selected_responses(branch)
    rows = db_session.scalars(
        select(ChatMessage)
        .join(selected, ChatMessage.id == selected.c.id)
        .where(
            ChatMessage.chat_session_id.in_([UUID(agent_id) for agent_id in agent_ids]),
        )
        .distinct(ChatMessage.chat_session_id)
        .order_by(ChatMessage.chat_session_id, ChatMessage.id.desc())
        .options(
            load_only(
                ChatMessage.id,
                ChatMessage.chat_session_id,
                ChatMessage.response_status,
            )
        )
    )
    return {str(row.chat_session_id): row for row in rows}


def latest_agent_response(
    db_session: Session, branch: ChatBranch, agent_id: str
) -> ChatMessage | None:
    return latest_agent_responses(db_session, branch, [agent_id]).get(agent_id)


def read_agent_completions(
    db_session: Session, response_ids: list[int]
) -> list[AgentCompletion]:
    """Read final output of authorized response IDs, without their execution trees."""
    if not response_ids:
        return []
    last_step = (
        select(ChatResponseItem.step_index)
        .where(ChatResponseItem.chat_message_id == ChatMessage.id)
        .order_by(ChatResponseItem.is_answer.desc(), ChatResponseItem.step_index.desc())
        .limit(1)
        .correlate(ChatMessage)
        .scalar_subquery()
    )
    rows = db_session.execute(
        select(ChatMessage, ChatResponseItem)
        .outerjoin(
            ChatResponseItem,
            and_(
                ChatResponseItem.chat_message_id == ChatMessage.id,
                ChatResponseItem.step_index == last_step,
            ),
        )
        .where(ChatMessage.id.in_(response_ids))
        .order_by(ChatMessage.id)
        .options(
            load_only(
                ChatMessage.id,
                ChatMessage.chat_session_id,
                ChatMessage.response_status,
                ChatMessage.response_failure,
            ),
            load_only(ChatResponseItem.message, ChatResponseItem.rendering),
        )
    ).all()
    ancestors = session_ancestors(
        db_session, [response.chat_session_id for response, _ in rows]
    )
    responses = {response.id: response for response, _ in rows}
    sources = _cited_sources(
        db_session,
        [
            (response.id, MessageRendering.model_validate(item.rendering))
            for response, item in rows
            if item is not None and item.rendering is not None
        ],
        lambda response_id: root_response_id(db_session, responses[response_id]),
    )
    completions: list[AgentCompletion] = []
    for response, item in rows:
        if response.response_status is None or not response.response_status.is_terminal:
            raise ValueError("Agent completion requires a terminal response")
        output = item.message if item is not None else None
        if output is not None and response.id in sources:
            output.metadata = ChatMessageMetadata(sources=sources[response.id])
        completions.append(
            AgentCompletion(
                agent_id=str(response.chat_session_id),
                agent_path=agent_path_from_ancestors(
                    response.chat_session_id, ancestors
                ),
                run_id=str(response.id),
                status=response.response_status,
                output=output,
                failure=response.response_failure,
            )
        )
    return completions


def _cited_sources(
    db_session: Session,
    renderings: list[tuple[int, MessageRendering]],
    root_id: Callable[[int], int],
) -> dict[int, dict[int, SavedSearchDoc]]:
    """Map each response's citation numbers to its cited documents.

    A child response's cited documents can be attached to its root response.
    """
    cited = {
        document_id
        for _, rendering in renderings
        for document_id in rendering.citation_documents.values()
    }
    if not cited:
        return {response_id: {} for response_id, _ in renderings}

    def read(message_ids: set[int]) -> dict[tuple[int, str], SavedSearchDoc]:
        return {
            (
                message_id,
                document.document_id,
            ): translate_db_search_doc_to_saved_search_doc(document)
            for message_id, document in db_session.execute(
                select(ChatMessage__SearchDoc.chat_message_id, StoredSearchDoc)
                .join(
                    StoredSearchDoc,
                    StoredSearchDoc.id == ChatMessage__SearchDoc.search_doc_id,
                )
                .where(
                    ChatMessage__SearchDoc.chat_message_id.in_(message_ids),
                    StoredSearchDoc.document_id.in_(cited),
                )
            )
        }

    documents = read({response_id for response_id, _ in renderings})
    missing = {
        response_id
        for response_id, rendering in renderings
        if any(
            (response_id, document_id) not in documents
            for document_id in rendering.citation_documents.values()
        )
    }
    roots = {response_id: root_id(response_id) for response_id in missing}
    if roots:
        documents.update(read(set(roots.values())))
    sources: dict[int, dict[int, SavedSearchDoc]] = {}
    for response_id, rendering in renderings:
        cited_sources = sources.setdefault(response_id, {})
        for number, document_id in rendering.citation_documents.items():
            document = documents.get((response_id, document_id))
            if document is None and response_id in roots:
                document = documents.get((roots[response_id], document_id))
            if document is None:
                raise ValueError("Cited source is unavailable on the response")
            cited_sources[number] = document
    return sources


def _selected_response_links(
    db_session: Session, branch: ChatBranch, agent_ids: list[UUID]
) -> dict[UUID, list[ResponseLink]]:
    """Read branch-visible response links once, then order each conversation."""
    if not agent_ids:
        return {}
    response_limits = {
        agent_id: len(branch.message_ids)
        if agent_id == branch.chat_session_id
        else MAX_AGENT_HISTORY_RUNS
        for agent_id in agent_ids
    }
    responses = selected_responses(branch)
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
            .limit(sum(response_limits.values()) + 1)
        )
        .mappings()
        .all()
    )
    links_by_agent: dict[UUID, list[ResponseLink]] = {
        agent_id: [] for agent_id in agent_ids
    }
    for link in TypeAdapter(list[ResponseLink]).validate_python(rows):
        links = links_by_agent[link.chat_session_id]
        links.append(link)
        if len(links) > response_limits[link.chat_session_id]:
            raise ValueError("Selected agent history exceeds its response limit")
    return {
        agent_id: links
        if agent_id == branch.chat_session_id
        else _order_response_links(links)
        for agent_id, links in links_by_agent.items()
    }


def _order_response_links(links: list[ResponseLink]) -> list[ResponseLink]:
    """Follow predecessors from the unique selected tip, newest response first."""
    if not links:
        return []
    predecessors = {link.previous_response_id for link in links}
    tips = [link for link in links if link.id not in predecessors]
    if len(tips) != 1:
        raise ValueError("Child history has ambiguous response selection")
    by_id = {link.id: link for link in links}
    selected: list[ResponseLink] = []
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
                        func.octet_length(cast(ChatResponseItem.message, Text)), 0
                    )
                    + func.coalesce(
                        func.octet_length(cast(ChatResponseItem.rendering, Text)), 0
                    )
                    + func.octet_length(cast(ChatResponseItem.inputs, Text))
                ),
                0,
            )
        )
        .where(ChatResponseItem.chat_message_id.in_(response_ids))
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
                selectinload(ChatMessage.response_items),
                selectinload(ChatMessage.tool_calls),
            )
        )
    }
    responses = [rows[link.id] for link in links]
    messages: list[Message] = []
    for response in reversed(responses):
        question = response.parent_message
        if question is None or question.chat_session_id != response.chat_session_id:
            raise ValueError("Response has no question in its conversation")
        if question.message_type == MessageType.USER:
            messages.append(
                UserMessage(
                    id=(
                        run_input_message_id(str(response.id), 0)
                        if question.invoking_tool_call_id is not None
                        else f"chat:{question.id}"
                    ),
                    content=question.message,
                )
            )
        elif question.message_type != MessageType.AGENT_RESULTS:
            raise ValueError("Response question is not a user or results message")
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
    for sources in _cited_sources(
        db_session,
        [
            (response.id, MessageRendering.model_validate(item.rendering))
            for response in reversed(responses)
            for item in response.response_items
            if item.rendering
        ],
        lambda response_id: by_id[response_id].root_id,
    ).values():
        restored.sources.update(sources)
    return restored


def load_agent_history(branch: ChatBranch, agent_id: str) -> SavedAgentContext:
    with get_session_with_current_tenant() as db_session:
        return _load_history(
            db_session, branch, visible_agent(db_session, branch, agent_id)
        )


def agent_metadata(
    agent: ChatSession,
    ancestors: dict[UUID, SessionAncestor],
    latest_response_id: int | None,
    status: RunStatus | None,
) -> AgentInfo:
    parent_id = ancestors[agent.id].parent_id
    return AgentInfo(
        id=str(agent.id),
        path=agent_path_from_ancestors(agent.id, ancestors),
        parent_id=str(parent_id) if parent_id else None,
        description=agent.description or "" if parent_id else "",
        restoration_config=agent.restoration_config,
        latest_run_id=str(latest_response_id)
        if latest_response_id is not None
        else None,
        status=status,
    )


def load_session_agent_metadata(
    message_id: int, *, branch: ChatBranch | None = None, include_root: bool = True
) -> list[AgentInfo]:
    """Read the agent tree visible on a branch: agents that visible responses spawned."""
    branch = branch if branch is not None else load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        responses = selected_responses(branch)
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
        latest_by_agent = latest_agent_responses(
            db_session,
            branch,
            [str(agent.id) for agent in agents if agent.id != branch.chat_session_id],
        )
        metadata: list[AgentInfo] = []
        for agent in agents:
            if agent.id == branch.chat_session_id:
                # Root discovery needs only the latest response, not its full history.
                latest_root = db_session.execute(
                    select(ChatMessage.id, ChatMessage.response_status)
                    .where(
                        ChatMessage.chat_session_id == branch.chat_session_id,
                        ChatMessage.id.in_(branch.message_ids),
                        ChatMessage.response_status.is_not(None),
                    )
                    .order_by(
                        case(
                            {
                                message_id: index
                                for index, message_id in enumerate(branch.message_ids)
                            },
                            value=ChatMessage.id,
                        )
                    )
                    .limit(1)
                ).one_or_none()
                latest_id, status = (
                    latest_root if latest_root is not None else (None, None)
                )
            else:
                latest = latest_by_agent.get(str(agent.id))
                latest_id = latest.id if latest else None
                status = latest.response_status if latest else None
            metadata.append(agent_metadata(agent, ancestors, latest_id, status))
        return metadata


def lookup_session_agent(
    branch: ChatBranch, agent_id: str, parent_agent_id: str
) -> AgentInfo | None:
    with get_session_with_current_tenant() as db_session:
        parent = visible_agent(db_session, branch, parent_agent_id)
        responses = selected_responses(branch)
        agent = db_session.scalar(
            select(ChatSession).where(
                ChatSession.id == UUID(agent_id),
                ChatSession.spawned_by_message_id.in_(select(responses.c.id)),
            )
        )
        if agent is None:
            return None
        ancestors = session_ancestors(db_session, [agent.id])
        if ancestors[agent.id].parent_id != parent.id:
            return None
        latest = latest_agent_response(db_session, branch, agent_id)
        return agent_metadata(
            agent,
            ancestors,
            latest.id if latest else None,
            latest.response_status if latest else None,
        )
