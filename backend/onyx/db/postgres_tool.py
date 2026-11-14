"""Agent-facing restricted query layer for the Postgres tool.

These functions back the `postgres_query` built-in tool: structured, ACL-safe
queries over a small allowlist of tables, as an alternative to semantic search
for questions about metadata, structure, counting, or the user's own history.

They are a distinct layer on top of the internal query helpers — filters are
explicit typed parameters (the tool schema is the column allowlist), every
query is capped and runs under a statement timeout, and each table applies its
own access-control mechanism (document ACL, hierarchy versioned filter,
chat ownership).
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from psycopg2.errors import QueryCanceled
from sqlalchemy import Select, and_, any_, distinct, func, select, true
from sqlalchemy.engine import Result
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource, MessageType
from onyx.db.document_access import apply_document_access_filter
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import escape_like_pattern
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    Connector,
    ConnectorCredentialPair,
    Document,
    HierarchyNode,
    SearchDoc,
)
from onyx.db.postgres_tool_models import GroupCount
from onyx.utils.variable_functionality import fetch_versioned_implementation

POSTGRES_TOOL_DEFAULT_LIMIT = 25
POSTGRES_TOOL_MAX_LIMIT = 100

# Substring filters are unindexed ILIKE scans and counts can join large tables;
# the tool runs synchronously in the chat loop, so a runaway query must die
# rather than stall the response.
_POSTGRES_TOOL_STATEMENT_TIMEOUT = "10s"


class PostgresToolQueryTimeoutError(Exception):
    """Raised when a tool query exceeds the statement timeout.

    The tool layer converts this into an LLM-facing "query too broad — narrow
    your filters" error.
    """


class DocumentGroupBy(str, Enum):
    SOURCE = "source"
    OWNER = "owner"


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, POSTGRES_TOOL_MAX_LIMIT))


def _execute_with_timeout(db_session: Session, stmt: Select) -> Result:
    """Execute under the tool's statement timeout.

    The timeout is transaction-local and stays in effect for the rest of the
    transaction — callers are expected to use a session dedicated to the tool
    query.
    """
    db_session.execute(
        select(
            func.set_config("statement_timeout", _POSTGRES_TOOL_STATEMENT_TIMEOUT, True)
        )
    )
    try:
        return db_session.execute(stmt)
    except OperationalError as e:
        if isinstance(e.orig, QueryCanceled):
            raise PostgresToolQueryTimeoutError(
                "Query exceeded the statement timeout"
            ) from e
        raise


def _ilike_contains(
    column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    substring: str,
) -> ColumnElement[bool]:
    pattern = f"%{escape_like_pattern(substring)}%"
    return column.ilike(pattern, escape="\\")


# ============================== Document ==============================


def _apply_document_filters(
    db_session: Session,
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None,
    prior_emails: list[str] | None,
    source_type: DocumentSource | None,
    title_contains: str | None,
    updated_after: datetime | None,
    updated_before: datetime | None,
    owned_by: str | None,
    parent_hierarchy_node_id: int | None,
    ensure_connector_join: bool = False,
) -> Select:
    """Apply the document ACL plus the allowlisted filters.

    `apply_document_access_filter` supplies the cc_pair joins, the DELETING
    cc_pair exclusion, and the permission checks; a document in multiple
    cc_pairs yields duplicate rows, so callers must dedupe (`.distinct()` /
    `count(distinct ...)`). `hidden` documents are excluded here — admins hid
    them from search, and this tool must not be a bypass.

    Date filters compare against `doc_updated_at` (source-updated time), so
    documents with an unknown source timestamp fall out of any date range.

    Source filtering (and source grouping) applies to the same joined cc_pair
    row as the ACL check, so a document is attributed to a source only when
    that source's cc_pair row grants access. This only diverges for a doc id
    shared across cc_pairs of *different* sources — practically nonexistent,
    since doc ids embed source-specific URLs/ids.
    """
    stmt = apply_document_access_filter(
        db_session,
        stmt,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
    )
    stmt = stmt.where(Document.hidden.is_(False))

    if source_type is not None or ensure_connector_join:
        stmt = stmt.join(
            Connector, Connector.id == ConnectorCredentialPair.connector_id
        )
    if source_type is not None:
        stmt = stmt.where(Connector.source == source_type)
    if title_contains is not None:
        stmt = stmt.where(_ilike_contains(Document.semantic_id, title_contains))
    if updated_after is not None:
        stmt = stmt.where(Document.doc_updated_at >= updated_after)
    if updated_before is not None:
        stmt = stmt.where(Document.doc_updated_at < updated_before)
    if owned_by is not None:
        stmt = stmt.where(any_(Document.primary_owners) == owned_by)
    if parent_hierarchy_node_id is not None:
        stmt = stmt.where(Document.parent_hierarchy_node_id == parent_hierarchy_node_id)
    return stmt


def query_documents_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: DocumentSource | None = None,
    title_contains: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: str | None = None,
    parent_hierarchy_node_id: int | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[tuple[Document, DocumentSource]]:
    """Accessible documents matching the filters with their connector source,
    newest first, capped."""
    stmt = select(Document, Connector.source)
    stmt = _apply_document_filters(
        db_session,
        stmt,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
        source_type=source_type,
        title_contains=title_contains,
        updated_after=updated_after,
        updated_before=updated_before,
        owned_by=owned_by,
        parent_hierarchy_node_id=parent_hierarchy_node_id,
        ensure_connector_join=True,
    )
    stmt = (
        stmt.distinct()
        .order_by(Document.doc_updated_at.desc().nulls_last(), Document.id.desc())
        .limit(_clamp_limit(limit))
    )
    # A doc visible through cc_pairs of two sources yields one row per source.
    rows: dict[str, tuple[Document, DocumentSource]] = {}
    for doc, source in _execute_with_timeout(db_session, stmt).tuples().all():
        rows.setdefault(doc.id, (doc, source))
    return list(rows.values())


def count_documents_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: DocumentSource | None = None,
    title_contains: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: str | None = None,
    parent_hierarchy_node_id: int | None = None,
) -> int:
    """Exact count of accessible documents matching the filters."""
    stmt = select(func.count(distinct(Document.id))).select_from(Document)
    stmt = _apply_document_filters(
        db_session,
        stmt,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
        source_type=source_type,
        title_contains=title_contains,
        updated_after=updated_after,
        updated_before=updated_before,
        owned_by=owned_by,
        parent_hierarchy_node_id=parent_hierarchy_node_id,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def count_documents_grouped_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    group_by: DocumentGroupBy,
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: DocumentSource | None = None,
    title_contains: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: str | None = None,
    parent_hierarchy_node_id: int | None = None,
) -> list[GroupCount]:
    """Accessible-document counts grouped by source or owner, largest first.

    Owner grouping unnests `primary_owners`: a document with several owners
    counts once per owner, and documents with no recorded owner are absent —
    so owner-group counts don't necessarily sum to the ungrouped total.

    Returns at most `POSTGRES_TOOL_MAX_LIMIT + 1` groups, so a caller can tell
    that the list was cut off.
    """
    count_col = func.count(distinct(Document.id)).label("count")

    group_col: InstrumentedAttribute[DocumentSource] | ColumnElement[str]
    if group_by == DocumentGroupBy.SOURCE:
        group_col = Connector.source
        stmt = select(group_col, count_col).select_from(Document)
    else:
        # Implicit-lateral set-returning function: unnest may reference the
        # document row it's joined against.
        owner_tv = (
            func.unnest(Document.primary_owners).table_valued("owner").render_derived()
        )
        group_col = owner_tv.c.owner
        stmt = select(group_col, count_col).select_from(Document).join(owner_tv, true())

    stmt = _apply_document_filters(
        db_session,
        stmt,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
        source_type=source_type,
        title_contains=title_contains,
        updated_after=updated_after,
        updated_before=updated_before,
        owned_by=owned_by,
        parent_hierarchy_node_id=parent_hierarchy_node_id,
        ensure_connector_join=group_by == DocumentGroupBy.SOURCE,
    )
    stmt = (
        stmt.group_by(group_col)
        .order_by(count_col.desc(), group_col.asc())
        .limit(POSTGRES_TOOL_MAX_LIMIT + 1)
    )

    rows = _execute_with_timeout(db_session, stmt).all()
    return [
        GroupCount(
            group=group.value if isinstance(group, DocumentSource) else str(group),
            count=count,
        )
        for group, count in rows
    ]


# ============================ HierarchyNode ============================


def _hierarchy_node_access_filter(
    db_session: Session,  # noqa: ARG001
    user_email: str | None,  # noqa: ARG001
    external_group_ids: list[str],  # noqa: ARG001
    user_id: UUID | None,  # noqa: ARG001
) -> ColumnElement[bool]:
    """MIT version: no permission filtering, matching `onyx.db.hierarchy`
    semantics (MIT has no permission sync). The EE version applies the
    hierarchy access filter."""
    return true()


def _get_hierarchy_node_access_filter(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None,
) -> ColumnElement[bool]:
    versioned_fn = fetch_versioned_implementation(
        "onyx.db.postgres_tool", "_hierarchy_node_access_filter"
    )
    return versioned_fn(db_session, user_email, external_group_ids, user_id)


def _apply_hierarchy_node_filters(
    stmt: Select,
    access_filter: ColumnElement[bool],
    *,
    source_type: DocumentSource | None,
    name_contains: str | None,
    parent_id: int | None,
    node_type: HierarchyNodeType | None,
) -> Select:
    # STUB nodes are internal placeholders and never surfaced (existing
    # precedent in hierarchy search).
    stmt = stmt.where(HierarchyNode.node_type != HierarchyNodeType.STUB, access_filter)

    if source_type is not None:
        stmt = stmt.where(HierarchyNode.source == source_type)
    if name_contains is not None:
        stmt = stmt.where(_ilike_contains(HierarchyNode.display_name, name_contains))
    if parent_id is not None:
        stmt = stmt.where(HierarchyNode.parent_id == parent_id)
    if node_type is not None:
        stmt = stmt.where(HierarchyNode.node_type == node_type)
    return stmt


def _query_hierarchy_nodes(
    db_session: Session,
    access_filter: ColumnElement[bool],
    *,
    source_type: DocumentSource | None = None,
    name_contains: str | None = None,
    parent_id: int | None = None,
    node_type: HierarchyNodeType | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[HierarchyNode]:
    stmt = select(HierarchyNode)
    stmt = _apply_hierarchy_node_filters(
        stmt,
        access_filter,
        source_type=source_type,
        name_contains=name_contains,
        parent_id=parent_id,
        node_type=node_type,
    )
    stmt = stmt.order_by(HierarchyNode.display_name, HierarchyNode.id).limit(
        _clamp_limit(limit)
    )
    return list(_execute_with_timeout(db_session, stmt).scalars().all())


def _count_hierarchy_nodes(
    db_session: Session,
    access_filter: ColumnElement[bool],
    *,
    source_type: DocumentSource | None = None,
    name_contains: str | None = None,
    parent_id: int | None = None,
    node_type: HierarchyNodeType | None = None,
) -> int:
    stmt = select(func.count()).select_from(HierarchyNode)
    stmt = _apply_hierarchy_node_filters(
        stmt,
        access_filter,
        source_type=source_type,
        name_contains=name_contains,
        parent_id=parent_id,
        node_type=node_type,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def query_hierarchy_nodes_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    source_type: DocumentSource | None = None,
    name_contains: str | None = None,
    parent_id: int | None = None,
    node_type: HierarchyNodeType | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[HierarchyNode]:
    """Accessible hierarchy nodes matching the filters, by display name, capped."""
    access_filter = _get_hierarchy_node_access_filter(
        db_session, user_email, external_group_ids, user_id
    )
    return _query_hierarchy_nodes(
        db_session,
        access_filter,
        source_type=source_type,
        name_contains=name_contains,
        parent_id=parent_id,
        node_type=node_type,
        limit=limit,
    )


def count_hierarchy_nodes_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    source_type: DocumentSource | None = None,
    name_contains: str | None = None,
    parent_id: int | None = None,
    node_type: HierarchyNodeType | None = None,
) -> int:
    """Exact count of accessible hierarchy nodes matching the filters."""
    access_filter = _get_hierarchy_node_access_filter(
        db_session, user_email, external_group_ids, user_id
    )
    return _count_hierarchy_nodes(
        db_session,
        access_filter,
        source_type=source_type,
        name_contains=name_contains,
        parent_id=parent_id,
        node_type=node_type,
    )


# ============================= ChatSession =============================


def _month_label(column: InstrumentedAttribute[datetime]) -> ColumnElement[str]:
    return func.to_char(column, "YYYY-MM")


def _owned_history_session(user_id: UUID | None) -> ColumnElement[bool]:
    """Sessions the user sees in their own chat history: owned, not
    soft-deleted, not incognito, and not a subagent's child session."""
    return and_(
        ChatSession.user_id == user_id,
        ChatSession.deleted.is_(False),
        ChatSession.incognito_record_mode.is_(None),
        ChatSession.spawned_by_message_id.is_(None),
    )


def _apply_chat_session_filters(
    stmt: Select,
    user_id: UUID | None,
    *,
    description_contains: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
    exclude_chat_session_id: UUID | None,
) -> Select:
    """Chat history is ownership-scoped: only the owner's sessions qualify.

    `user_id` None means an auth-disabled deployment where sessions are stored
    with NULL user_id (`==` renders IS NULL). OnyxBot (Slack) sessions are
    included deliberately — they are still the user's own history. `exclude_chat_session_id` drops the
    in-flight conversation, which would otherwise top-hit any search about
    itself (the user's question is persisted before the tool runs).
    """
    stmt = stmt.where(_owned_history_session(user_id))
    if description_contains is not None:
        stmt = stmt.where(
            _ilike_contains(ChatSession.description, description_contains)
        )
    if created_after is not None:
        stmt = stmt.where(ChatSession.time_created >= created_after)
    if created_before is not None:
        stmt = stmt.where(ChatSession.time_created < created_before)
    if exclude_chat_session_id is not None:
        stmt = stmt.where(ChatSession.id != exclude_chat_session_id)
    return stmt


def query_chat_sessions_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    description_contains: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[ChatSession]:
    """The user's chat sessions matching the filters, newest first, capped."""
    stmt = select(ChatSession)
    stmt = _apply_chat_session_filters(
        stmt,
        user_id,
        description_contains=description_contains,
        created_after=created_after,
        created_before=created_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    stmt = stmt.order_by(ChatSession.time_created.desc(), ChatSession.id.desc()).limit(
        _clamp_limit(limit)
    )
    return list(_execute_with_timeout(db_session, stmt).scalars().all())


def count_chat_sessions_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    description_contains: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
) -> int:
    """Exact count of the user's chat sessions matching the filters."""
    stmt = select(func.count()).select_from(ChatSession)
    stmt = _apply_chat_session_filters(
        stmt,
        user_id,
        description_contains=description_contains,
        created_after=created_after,
        created_before=created_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def count_chat_sessions_by_month_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    description_contains: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
) -> list[GroupCount]:
    """Per-month (YYYY-MM of creation) counts of matching sessions, newest first."""
    month_col = _month_label(ChatSession.time_created).label("month")
    count_col = func.count().label("count")
    stmt = select(month_col, count_col).select_from(ChatSession)
    stmt = _apply_chat_session_filters(
        stmt,
        user_id,
        description_contains=description_contains,
        created_after=created_after,
        created_before=created_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    stmt = stmt.group_by(month_col).order_by(month_col.desc())
    rows = _execute_with_timeout(db_session, stmt).all()
    return [GroupCount(group=month, count=count) for month, count in rows]


# ============================= ChatMessage =============================


def _apply_chat_message_filters(
    stmt: Select,
    user_id: UUID | None,
    *,
    chat_session_id: UUID | None,
    content_contains: str | None,
    message_type: MessageType | None,
    sent_after: datetime | None,
    sent_before: datetime | None,
    exclude_chat_session_id: UUID | None,
) -> Select:
    """Ownership is enforced by joining through the message's session (same
    semantics as `_apply_chat_session_filters`).

    Only USER/ASSISTANT messages with non-empty content qualify: the first
    message of every session is an empty root node, and SYSTEM /
    TOOL_CALL_RESPONSE rows are plumbing, not conversation. Edited-away tree
    branches may still surface — acceptable; they were real messages.
    """
    stmt = stmt.join(ChatSession, ChatMessage.chat_session_id == ChatSession.id).where(
        _owned_history_session(user_id),
        ChatMessage.message_type.in_([MessageType.USER, MessageType.ASSISTANT]),
        ChatMessage.message != "",
    )
    if chat_session_id is not None:
        stmt = stmt.where(ChatMessage.chat_session_id == chat_session_id)
    if content_contains is not None:
        stmt = stmt.where(_ilike_contains(ChatMessage.message, content_contains))
    if message_type is not None:
        stmt = stmt.where(ChatMessage.message_type == message_type)
    if sent_after is not None:
        stmt = stmt.where(ChatMessage.time_sent >= sent_after)
    if sent_before is not None:
        stmt = stmt.where(ChatMessage.time_sent < sent_before)
    if exclude_chat_session_id is not None:
        stmt = stmt.where(ChatMessage.chat_session_id != exclude_chat_session_id)
    return stmt


def query_chat_messages_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    chat_session_id: UUID | None = None,
    content_contains: str | None = None,
    message_type: MessageType | None = None,
    sent_after: datetime | None = None,
    sent_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[ChatMessage]:
    """The user's chat messages matching the filters, newest first, capped."""
    stmt = select(ChatMessage)
    stmt = _apply_chat_message_filters(
        stmt,
        user_id,
        chat_session_id=chat_session_id,
        content_contains=content_contains,
        message_type=message_type,
        sent_after=sent_after,
        sent_before=sent_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    stmt = stmt.order_by(ChatMessage.time_sent.desc(), ChatMessage.id.desc()).limit(
        _clamp_limit(limit)
    )
    return list(_execute_with_timeout(db_session, stmt).scalars().all())


def count_chat_messages_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    chat_session_id: UUID | None = None,
    content_contains: str | None = None,
    message_type: MessageType | None = None,
    sent_after: datetime | None = None,
    sent_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
) -> int:
    """Exact count of the user's chat messages matching the filters."""
    stmt = select(func.count()).select_from(ChatMessage)
    stmt = _apply_chat_message_filters(
        stmt,
        user_id,
        chat_session_id=chat_session_id,
        content_contains=content_contains,
        message_type=message_type,
        sent_after=sent_after,
        sent_before=sent_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def count_chat_messages_by_month_for_tool(
    db_session: Session,
    user_id: UUID | None,
    *,
    chat_session_id: UUID | None = None,
    content_contains: str | None = None,
    message_type: MessageType | None = None,
    sent_after: datetime | None = None,
    sent_before: datetime | None = None,
    exclude_chat_session_id: UUID | None = None,
) -> list[GroupCount]:
    """Per-month (YYYY-MM sent) counts of matching messages, newest first."""
    month_col = _month_label(ChatMessage.time_sent).label("month")
    count_col = func.count().label("count")
    stmt = select(month_col, count_col).select_from(ChatMessage)
    stmt = _apply_chat_message_filters(
        stmt,
        user_id,
        chat_session_id=chat_session_id,
        content_contains=content_contains,
        message_type=message_type,
        sent_after=sent_after,
        sent_before=sent_before,
        exclude_chat_session_id=exclude_chat_session_id,
    )
    stmt = stmt.group_by(month_col).order_by(month_col.desc())
    rows = _execute_with_timeout(db_session, stmt).all()
    return [GroupCount(group=month, count=count) for month, count in rows]


# ============================== SearchDoc ==============================


def _get_owned_chat_message(
    db_session: Session,
    user_id: UUID | None,
    chat_message_id: int,
) -> ChatMessage | None:
    """The message, only if it belongs to one of the user's history sessions."""
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(
            ChatMessage.id == chat_message_id,
            _owned_history_session(user_id),
        )
    )
    return _execute_with_timeout(db_session, stmt).scalar_one_or_none()


def _cited_search_doc_ids(message: ChatMessage) -> list[int]:
    """SearchDoc ids actually cited by the message, in citation-number order.

    `citations` maps citation number -> SearchDoc id; JSONB round-trips the
    integer keys as strings.
    """
    citations = message.citations or {}
    return [
        int(search_doc_id)
        for _, search_doc_id in sorted(citations.items(), key=lambda kv: int(kv[0]))
    ]


def query_search_docs_for_tool(
    db_session: Session,
    user_id: UUID | None,
    chat_message_id: int,
    *,
    cited_only: bool = True,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> list[SearchDoc]:
    """SearchDoc snapshots for a past message the user owns.

    A SearchDoc is a point-in-time retrieval snapshot with no ACL columns of
    its own — access is scoped purely by ownership of the message, never by
    re-checking the live Document's ACL (the user already saw this content).

    `cited_only` (default) returns the docs the answer actually cited, in
    citation order; `cited_only=False` widens to everything retrieved for the
    message. Returns empty if the message isn't the user's.
    """
    message = _get_owned_chat_message(db_session, user_id, chat_message_id)
    if message is None:
        return []

    if cited_only:
        ordered_ids = _cited_search_doc_ids(message)[: _clamp_limit(limit)]
        if not ordered_ids:
            return []
        docs = (
            _execute_with_timeout(
                db_session, select(SearchDoc).where(SearchDoc.id.in_(ordered_ids))
            )
            .scalars()
            .all()
        )
        docs_by_id = {doc.id: doc for doc in docs}
        return [docs_by_id[i] for i in ordered_ids if i in docs_by_id]

    stmt = (
        select(SearchDoc)
        .join(
            ChatMessage__SearchDoc,
            ChatMessage__SearchDoc.search_doc_id == SearchDoc.id,
        )
        .where(ChatMessage__SearchDoc.chat_message_id == chat_message_id)
        .order_by(SearchDoc.id)
        .limit(_clamp_limit(limit))
    )
    return list(_execute_with_timeout(db_session, stmt).scalars().all())


def count_search_docs_for_tool(
    db_session: Session,
    user_id: UUID | None,
    chat_message_id: int,
    *,
    cited_only: bool = True,
) -> int:
    """Count of cited (default) or retrieved SearchDocs for a message the user owns."""
    message = _get_owned_chat_message(db_session, user_id, chat_message_id)
    if message is None:
        return 0

    if cited_only:
        return len(_cited_search_doc_ids(message))

    stmt = (
        select(func.count())
        .select_from(ChatMessage__SearchDoc)
        .where(ChatMessage__SearchDoc.chat_message_id == chat_message_id)
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()
