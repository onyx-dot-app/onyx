"""Select child sessions and restore their branch-visible conversation context."""

from collections.abc import Collection
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import (
    Integer,
    Select,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    true,
)
from sqlalchemy.orm import (
    Session,
    aliased,
    joinedload,
    load_only,
    raiseload,
    selectinload,
)
from sqlalchemy.sql.selectable import CTE

from onyx.agents.execution_records import run_input_message_id
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    InputSource,
    RunStatus,
    messages_from_steps,
)
from onyx.chat.models import (
    MAX_DISCOVERED_AGENTS,
    ChatBackgroundActivity,
    ChatBranch,
    ChatMessageMetadata,
    MessageRendering,
    ResponseLink,
    SavedAgentContext,
    SessionAncestor,
)
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    MAX_AGENT_DEPTH,
    MAX_AGENT_HISTORY_RUNS,
    agent_path_from_ancestors,
    checkpoint_from_summary,
    find_summary_for_ancestry,
    get_selected_response,
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
    ChatInput,
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
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME

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


def _selected_responses(branch: ChatBranch) -> CTE:
    """Follow branch-visible invocations without loading response payloads."""
    question = aliased(ChatMessage)
    previous = aliased(ChatMessage)
    responses = (
        select(
            ChatMessage.id,
            ChatMessage.chat_session_id,
            case(
                (question.message_type == MessageType.ASSISTANT, question.id),
                (previous.response_status.is_not(None), question.parent_message_id),
                else_=None,
            ).label("previous_response_id"),
            ChatMessage.id.label("root_id"),
            ChatMessage.response_status.label("status"),
            literal(0).label("depth"),
            cast(literal(None), Integer).label("invocation_id"),
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
    # Restrict each edge lookup to the current response before combining them.
    edges = (
        select(
            ChatMessage.id.label("id"),
            question.parent_message_id.label("previous_response_id"),
            ToolCall.id.label("invocation_id"),
            literal(1).label("depth_increment"),
        )
        .join(question, ChatMessage.parent_message_id == question.id)
        .join(ToolCall, question.invoking_tool_call_id == ToolCall.id)
        .where(ToolCall.parent_chat_message_id == responses.c.id)
        .correlate(responses)
        .union_all(
            select(
                ChatMessage.id,
                ChatMessage.parent_message_id,
                cast(literal(None), Integer),
                literal(0),
            )
            .where(
                ChatMessage.parent_message_id == responses.c.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
                ChatMessage.chat_session_id == responses.c.chat_session_id,
                ChatMessage.chat_session_id != branch.chat_session_id,
            )
            .correlate(responses)
        )
        .lateral("response_edges")
    )
    responses = responses.union_all(
        select(
            ChatMessage.id,
            ChatMessage.chat_session_id,
            edges.c.previous_response_id,
            responses.c.root_id,
            ChatMessage.response_status,
            responses.c.depth + edges.c.depth_increment,
            func.coalesce(edges.c.invocation_id, responses.c.invocation_id),
        )
        .select_from(responses)
        .join(edges, true())
        .join(ChatMessage, ChatMessage.id == edges.c.id)
        .where(
            ChatMessage.response_status.is_not(None),
            responses.c.depth + edges.c.depth_increment <= MAX_AGENT_DEPTH,
        )
    )
    return responses


def _unread_agent_results(selected: CTE) -> Select[tuple[int, RunStatus | None, UUID]]:
    recipient_history = selected.alias("recipient_history")
    later_revision = selected.alias("later_revision")
    invocation = aliased(ToolCall)
    generation = aliased(ChatResponseItem)
    instructed_response = selected.alias("instructed_response")
    sender_response = selected.alias("sender_response")
    # An accepted instruction also gives its sender a result, including when
    # the instruction joins a run originally started by another ancestor.
    recipients = (
        select(selected.c.id, selected.c.invocation_id)
        .union(
            select(selected.c.id, ChatInput.invoking_tool_call_id)
            .select_from(selected)
            .join(
                instructed_response,
                instructed_response.c.invocation_id == selected.c.invocation_id,
            )
            .join(
                ChatResponseItem,
                ChatResponseItem.chat_message_id == instructed_response.c.id,
            )
            .join(ChatInput, ChatInput.response_item_id == ChatResponseItem.id)
            .join(ToolCall, ChatInput.invoking_tool_call_id == ToolCall.id)
            .join(
                sender_response, sender_response.c.id == ToolCall.parent_chat_message_id
            )
            .where(ChatInput.source == InputSource.AGENT)
        )
        .subquery("result_recipients")
    )
    accepted = (
        select(ChatInput.id)
        .join(ChatResponseItem, ChatInput.response_item_id == ChatResponseItem.id)
        .join(
            recipient_history,
            ChatResponseItem.chat_message_id == recipient_history.c.id,
        )
        .where(
            ChatInput.source == InputSource.AGENT_RESULT,
            ChatInput.source_response_id == ChatMessage.id,
            recipient_history.c.chat_session_id == invocation.chat_session_id,
        )
        .correlate(ChatMessage, invocation)
        .exists()
    )
    return (
        select(
            ChatMessage.id,
            ChatMessage.response_status.label("status"),
            invocation.chat_session_id.label("recipient_id"),
        )
        .distinct()
        .join(selected, selected.c.id == ChatMessage.id)
        .join(recipients, recipients.c.id == ChatMessage.id)
        .join(invocation, recipients.c.invocation_id == invocation.id)
        .join(
            generation,
            and_(
                generation.chat_message_id == invocation.parent_chat_message_id,
                generation.step_index == invocation.turn_number,
            ),
        )
        .where(
            ~select(later_revision.c.id)
            .where(
                later_revision.c.invocation_id == selected.c.invocation_id,
                later_revision.c.id > selected.c.id,
            )
            .correlate(selected)
            .exists(),
            ~accepted,
            or_(
                *[
                    generation.message["content"].contains(
                        func.jsonb_build_array(
                            func.jsonb_build_object(
                                "type",
                                "tool_call",
                                "id",
                                invocation.tool_call_id,
                                "name",
                                name,
                            )
                        )
                    )
                    for name in (SPAWN_AGENT_TOOL_NAME, "send_message", "queue_message")
                ]
            ),
        )
    )


def background_response_statuses(
    db_session: Session,
    branch: ChatBranch,
    parent_agent_id: str,
    received_run_ids: Collection[str],
) -> dict[int, RunStatus]:
    """Read unread results from spawned or instructed descendants; does not commit."""
    unread = _unread_agent_results(_selected_responses(branch)).subquery()
    rows = db_session.execute(
        select(unread.c.id, unread.c.status)
        .where(
            unread.c.recipient_id == UUID(parent_agent_id),
            unread.c.id.not_in(
                [int(run_id) for run_id in received_run_ids if run_id.isdecimal()]
            ),
        )
        .order_by(
            case(
                (
                    unread.c.status.in_(
                        [status for status in RunStatus if status.is_terminal]
                    ),
                    0,
                ),
                else_=1,
            ),
            unread.c.id,
        )
        .limit(MAX_DISCOVERED_AGENTS)
    )
    return {response_id: status for response_id, status in rows if status is not None}


def pending_agent_completion_ids(db_session: Session, branch: ChatBranch) -> list[int]:
    """Read idle recipients with unread results, without loading response content."""
    selected = _selected_responses(branch)
    latest = (
        select(selected.c.chat_session_id, func.max(selected.c.id).label("id"))
        .group_by(selected.c.chat_session_id)
        .subquery()
    )
    # Reuse one CTE within the statement, including the unread-result predicate.
    unread = _unread_agent_results(selected).subquery()
    rows = db_session.scalars(
        select(ChatMessage.id)
        .join(latest, latest.c.id == ChatMessage.id)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.response_status == RunStatus.COMPLETE,
            ChatSession.deleted.is_(False),
            or_(
                ChatSession.id == branch.chat_session_id,
                ChatSession.restoration_config["kind"].as_string().is_not(None),
            ),
            ChatMessage.chat_session_id.in_(
                select(unread.c.recipient_id).where(
                    unread.c.status.in_(
                        [status for status in RunStatus if status.is_terminal]
                    )
                )
            ),
        )
    )
    return list(rows)


def unread_agent_result_ids(
    db_session: Session, branch: ChatBranch, agent_id: str
) -> list[int]:
    statuses = background_response_statuses(db_session, branch, agent_id, ())
    return [
        response_id for response_id, status in statuses.items() if status.is_terminal
    ]


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
            raiseload(ChatResponseItem.inputs),
        )
    ).all()
    ancestors = session_ancestors(
        db_session, [response.chat_session_id for response, _ in rows]
    )
    renderings = {
        response.id: MessageRendering.model_validate(item.rendering)
        for response, item in rows
        if item is not None and item.rendering is not None
    }
    cited_document_ids = {
        document_id
        for rendering in renderings.values()
        for document_id in rendering.citation_documents.values()
    }
    document_query = (
        select(ChatMessage__SearchDoc.chat_message_id, StoredSearchDoc)
        .join(
            StoredSearchDoc, StoredSearchDoc.id == ChatMessage__SearchDoc.search_doc_id
        )
        .where(StoredSearchDoc.document_id.in_(cited_document_ids))
    )
    documents = (
        {
            (
                response_id,
                document.document_id,
            ): translate_db_search_doc_to_saved_search_doc(document)
            for response_id, document in db_session.execute(
                document_query.where(
                    ChatMessage__SearchDoc.chat_message_id.in_(response_ids)
                )
            )
        }
        if cited_document_ids
        else {}
    )
    # Older child responses attached their cited documents to the root response.
    legacy_roots = {
        response.id: root_response_id(db_session, response)
        for response, _ in rows
        if (rendering := renderings.get(response.id)) is not None
        and any(
            (response.id, document_id) not in documents
            for document_id in rendering.citation_documents.values()
        )
    }
    if legacy_roots:
        documents.update(
            {
                (
                    response_id,
                    document.document_id,
                ): translate_db_search_doc_to_saved_search_doc(document)
                for response_id, document in db_session.execute(
                    document_query.where(
                        ChatMessage__SearchDoc.chat_message_id.in_(
                            set(legacy_roots.values())
                        )
                    )
                )
            }
        )
    completions: list[AgentCompletion] = []
    for response, item in rows:
        if response.response_status is None or not response.response_status.is_terminal:
            raise ValueError("Agent completion requires a terminal response")
        output = item.message if item is not None else None
        rendering = renderings.get(response.id)
        if output is not None and rendering is not None:
            sources = {}
            for number, document_id in rendering.citation_documents.items():
                document = documents.get((response.id, document_id))
                if document is None and response.id in legacy_roots:
                    document = documents.get((legacy_roots[response.id], document_id))
                if document is None:
                    raise ValueError("Cited source is unavailable on the response")
                sources[number] = document
            output.metadata = ChatMessageMetadata(sources=sources)
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
        select(
            item_bytes
            + tool_bytes
            + input_bytes
            + select(func.coalesce(func.sum(func.octet_length(ChatInput.content)), 0))
            .join(ChatResponseItem, ChatInput.response_item_id == ChatResponseItem.id)
            .where(ChatResponseItem.chat_message_id.in_(response_ids))
            .scalar_subquery()
        )
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
            raise ValueError("Response has no predecessor in its conversation")
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
        elif question.message_type != MessageType.ASSISTANT:
            raise ValueError("Response predecessor is not a user or assistant message")
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
    sources = {
        response.id: {
            doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
            for doc in response.search_docs
        }
        for response in db_session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.id.in_({link.root_id for link in links} | set(response_ids))
            )
            .options(selectinload(ChatMessage.search_docs))
        )
    }
    for response in reversed(responses):
        root_id = by_id[response.id].root_id
        if root_id not in sources:
            raise ValueError("Root response is unavailable")
        documents = {**sources[root_id], **sources.get(response.id, {})}
        for item in response.response_items:
            if item.rendering:
                rendering = MessageRendering.model_validate(item.rendering)
                for number, document_id in rendering.citation_documents.items():
                    document = documents.get(document_id)
                    if document is None:
                        raise ValueError("Cited source is unavailable on the response")
                    restored.sources[number] = document
    return restored


def load_agent_history(message_id: int, agent_id: str) -> SavedAgentContext:
    branch = load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        return _load_history(
            db_session, branch, _visible_agent(db_session, branch, agent_id)
        )


def _agent_metadata(
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
        # Keep the ancestry needed to reach descendants outside the recent-agent limit.
        missing_ids = ancestors.keys() - set(agent_ids)
        if not include_root:
            missing_ids.discard(branch.chat_session_id)
        if missing_ids:
            agents.extend(
                db_session.scalars(
                    select(ChatSession).where(ChatSession.id.in_(missing_ids))
                )
            )
        links = _selected_response_links(
            db_session,
            branch,
            [agent.id for agent in agents if agent.id != branch.chat_session_id],
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
                latest = links[agent.id][0] if links[agent.id] else None
                latest_id = latest.id if latest else None
                status = latest.status if latest else None
            metadata.append(_agent_metadata(agent, ancestors, latest_id, status))
        return metadata


def lookup_session_agent(
    message_id: int, agent_id: str, parent_agent_id: str
) -> AgentInfo | None:
    branch = load_chat_branch(message_id)
    with get_session_with_current_tenant() as db_session:
        parent = _visible_agent(db_session, branch, parent_agent_id)
        responses = _selected_responses(branch)
        agent = db_session.scalar(
            select(ChatSession).where(
                ChatSession.id == UUID(agent_id),
                ChatSession.spawned_by_message_id.in_(select(responses.c.id)),
            )
        )
        if agent is None:
            return None
        ancestors = session_ancestors(db_session, [agent.id])
        if parent.id == agent.id or parent.id not in ancestors:
            return None
        links = _selected_response_links(db_session, branch, [agent.id])[agent.id]
        latest = links[0] if links else None
        return _agent_metadata(
            agent,
            ancestors,
            latest.id if latest else None,
            latest.status if latest else None,
        )


def active_subagent_response_ids(db_session: Session, branch: ChatBranch) -> list[int]:
    """Read running descendants on the selected branch without their content."""
    responses = _selected_responses(branch)
    return list(
        db_session.scalars(
            select(responses.c.id)
            .where(
                responses.c.chat_session_id != branch.chat_session_id,
                responses.c.status == RunStatus.RUNNING,
            )
            .distinct()
        )
    )


def read_chat_background_activity(
    session: Session, chat_session: ChatSession
) -> ChatBackgroundActivity:
    """Read selected response and descendant work after session authorization."""
    selected = get_selected_response(session, chat_session.id)
    if selected is None:
        return ChatBackgroundActivity()
    if chat_session.incognito_record_mode is not None or chat_session.deleted:
        return ChatBackgroundActivity(latest_response_id=selected.id)
    if (
        session.scalar(
            select(ChatSession.id)
            .join(ChatMessage, ChatSession.spawned_by_message_id == ChatMessage.id)
            .where(ChatMessage.chat_session_id == chat_session.id)
            .limit(1)
        )
        is None
    ):
        return ChatBackgroundActivity(latest_response_id=selected.id)
    branch = ChatBranch(
        chat_session_id=chat_session.id,
        message_ids=visible_message_ids(session, selected),
    )
    recipients = pending_agent_completion_ids(session, branch)
    return ChatBackgroundActivity(
        latest_response_id=selected.id,
        running_response_ids=active_subagent_response_ids(session, branch),
        has_pending_root_results=selected.id in recipients,
        completion_host_response_ids=(
            list(
                session.scalars(
                    select(ChatMessage.id).where(
                        ChatMessage.id.in_(branch.message_ids),
                        ChatMessage.message_type == MessageType.ASSISTANT,
                    )
                )
            )
            if any(response_id != selected.id for response_id in recipients)
            else []
        ),
    )
