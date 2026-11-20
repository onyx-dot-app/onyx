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

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from psycopg2.errors import QueryCanceled
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Select,
    String,
    and_,
    cast,
    distinct,
    exists,
    false,
    func,
    or_,
    select,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Result
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import CTE

from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import TimeRange
from onyx.db.document_access import (
    apply_resolved_document_access_filter,
    resolve_document_access_pairs,
)
from onyx.db.enums import ConnectorCredentialPairStatus, HierarchyNodeType
from onyx.db.hierarchy import escape_like_pattern, hierarchy_node_own_document_id
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    Connector,
    ConnectorCredentialPair,
    Document,
    Document__Tag,
    DocumentByConnectorCredentialPair,
    DocumentSet,
    DocumentSet__ConnectorCredentialPair,
    HierarchyNode,
    SearchDoc,
)
from onyx.db.models import Tag as TagRow
from onyx.db.postgres_tool_models import (
    DocumentCursor,
    DocumentOrder,
    DocumentScope,
    GroupCount,
)
from onyx.document_index.opensearch.constants import ASSUMED_DOCUMENT_AGE_DAYS
from onyx.utils.variable_functionality import fetch_versioned_implementation

POSTGRES_TOOL_DEFAULT_LIMIT = 25
POSTGRES_TOOL_MAX_LIMIT = 100

# Substring filters are unindexed ILIKE scans and counts can join large tables;
# the tool runs synchronously in the chat loop, so a runaway query must die
# rather than stall the response.
_POSTGRES_TOOL_STATEMENT_TIMEOUT = "10s"
# A listing's total is extra information; it must not make a cheap first page
# slow or fail it.
_OPTIONAL_COUNT_TIMEOUT = "2s"


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


@contextmanager
def _timeouts_as_tool_errors() -> Iterator[None]:
    try:
        yield
    except OperationalError as e:
        if isinstance(e.orig, QueryCanceled):
            raise PostgresToolQueryTimeoutError(
                "Query exceeded the statement timeout"
            ) from e
        raise


@contextmanager
def tool_transaction(db_session: Session) -> Iterator[None]:
    """Run a tool call's read. One snapshot covers the access pairs that a
    document query resolves first and the rows they then filter, so a pair
    revoked in between cannot grant. The statement timeout covers every
    statement, the access lookups included, and each timeout raises
    PostgresToolQueryTimeoutError."""
    with _timeouts_as_tool_errors():
        db_session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        db_session.execute(
            select(
                func.set_config(
                    "statement_timeout", _POSTGRES_TOOL_STATEMENT_TIMEOUT, True
                )
            )
        )
        yield


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
    substrings: list[str],
) -> ColumnElement[bool]:
    """The column contains any of the substrings."""
    return or_(
        *(
            column.ilike(f"%{escape_like_pattern(substring)}%", escape="\\")
            for substring in substrings
        )
    )


# =========================== Knowledge scope ===========================


def _hierarchy_subtree(node_ids: list[int]) -> CTE:
    """The given hierarchy nodes and all their descendants. UNION drops repeated
    rows, so a cycle in `parent_id` ends the walk."""
    subtree = (
        select(HierarchyNode.id)
        .where(HierarchyNode.id.in_(node_ids))
        .cte("knowledge_subtree", recursive=True)
    )
    child = aliased(HierarchyNode)
    return subtree.union(
        select(child.id).join(subtree, child.parent_id == subtree.c.id)
    )


def _scope_subtree(scope: DocumentScope) -> CTE | None:
    if not scope.hierarchy_node_ids:
        return None
    return _hierarchy_subtree(scope.hierarchy_node_ids)


def _document_knowledge_filter(
    scope: DocumentScope, subtree: CTE | None
) -> ColumnElement[bool]:
    """A document is in the knowledge when any knowledge element matches it.
    `subtree` is `_hierarchy_subtree` of the scope's nodes, built once per
    statement because a CTE name must be unique in it."""
    clauses: list[ColumnElement[bool]] = []
    if scope.document_set_names:
        # Any of the document's cc_pairs counts, as for the document sets that
        # sync writes to the index (`fetch_document_sets_for_documents`).
        doc_cc = aliased(DocumentByConnectorCredentialPair)
        cc_pair = aliased(ConnectorCredentialPair)
        clauses.append(
            exists(
                select(1)
                .select_from(doc_cc)
                .join(
                    cc_pair,
                    and_(
                        doc_cc.connector_id == cc_pair.connector_id,
                        doc_cc.credential_id == cc_pair.credential_id,
                    ),
                )
                .join(
                    DocumentSet__ConnectorCredentialPair,
                    and_(
                        DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
                        == cc_pair.id,
                        DocumentSet__ConnectorCredentialPair.is_current.is_(True),
                    ),
                )
                .join(
                    DocumentSet,
                    DocumentSet.id
                    == DocumentSet__ConnectorCredentialPair.document_set_id,
                )
                .where(
                    doc_cc.id == Document.id,
                    cc_pair.status != ConnectorCredentialPairStatus.DELETING,
                    DocumentSet.name.in_(scope.document_set_names),
                )
            )
        )
    if scope.attached_document_ids:
        clauses.append(Document.id.in_(scope.attached_document_ids))
    if subtree is not None:
        clauses.append(Document.parent_hierarchy_node_id.in_(select(subtree.c.id)))
        # A selected node can itself be a document, such as a Confluence page.
        own_document_id = hierarchy_node_own_document_id()
        clauses.append(
            Document.id.in_(
                select(own_document_id).where(
                    HierarchyNode.id.in_(scope.hierarchy_node_ids),
                    own_document_id.is_not(None),
                )
            )
        )
    return or_(*clauses) if clauses else false()


def _date_range_filter(
    column: InstrumentedAttribute[datetime | None],
    time_range: TimeRange,
    *,
    include_undated: bool,
) -> ColumnElement[bool]:
    bounds: list[ColumnElement[bool]] = []
    if time_range.start is not None:
        bounds.append(column >= time_range.start)
    if time_range.end is not None:
        bounds.append(column <= time_range.end)
    in_range = and_(*bounds)
    return or_(column.is_(None), in_range) if include_undated else in_range


def _document_scope_filter(scope: DocumentScope) -> ColumnElement[bool]:
    """The knowledge clause ANDed with the request filters, except source
    types: those limit the pairs that grant access (`_document_source_types`)."""
    clauses: list[ColumnElement[bool]] = []
    if scope.restricts_knowledge:
        clauses.append(_document_knowledge_filter(scope, _scope_subtree(scope)))
    # Undated documents follow the search filter: a created range keeps them,
    # and an updated range keeps them only for an old, open-ended start.
    created = scope.created_at_range
    if created is not None and created.has_bounds():
        clauses.append(
            _date_range_filter(Document.doc_created_at, created, include_undated=True)
        )
    updated = scope.updated_at_range
    if updated is not None and updated.has_bounds():
        old_open_start = (
            updated.start is not None
            and updated.end is None
            and updated.start
            < datetime.now(timezone.utc) - timedelta(days=ASSUMED_DOCUMENT_AGE_DAYS)
        )
        clauses.append(
            _date_range_filter(
                Document.doc_updated_at, updated, include_undated=old_open_start
            )
        )
    if scope.tags:
        clauses.append(
            exists(
                select(1)
                .select_from(Document__Tag)
                .join(TagRow, TagRow.id == Document__Tag.tag_id)
                .where(
                    Document__Tag.document_id == Document.id,
                    or_(
                        *(
                            and_(
                                TagRow.tag_key == tag.tag_key,
                                TagRow.tag_value == tag.tag_value,
                            )
                            for tag in scope.tags
                        )
                    ),
                )
            )
        )
    return and_(true(), *clauses)


def _hierarchy_scope_filter(scope: DocumentScope) -> ColumnElement[bool]:
    """Folders in the selected subtrees, or that directly hold a document in
    the knowledge."""
    clauses: list[ColumnElement[bool]] = []
    if scope.source_types is not None:
        clauses.append(HierarchyNode.source.in_(scope.source_types))
    if scope.restricts_knowledge:
        knowledge: list[ColumnElement[bool]] = []
        subtree = _scope_subtree(scope)
        if subtree is not None:
            knowledge.append(HierarchyNode.id.in_(select(subtree.c.id)))
        if scope.has_document_knowledge:
            knowledge.append(
                HierarchyNode.id.in_(
                    select(Document.parent_hierarchy_node_id).where(
                        _document_knowledge_filter(scope, subtree)
                    )
                )
            )
        clauses.append(or_(*knowledge) if knowledge else false())
    return and_(true(), *clauses)


# ============================== Document ==============================


def _document_source_types(
    source_type: list[DocumentSource] | None, scope: DocumentScope | None
) -> list[DocumentSource] | None:
    """The sources the request and the scope both allow; None allows all."""
    scope_sources = scope.source_types if scope is not None else None
    if source_type is None:
        return scope_sources
    if scope_sources is None:
        return source_type
    return [source for source in source_type if source in scope_sources]


def _apply_document_filters(
    db_session: Session,
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None,
    prior_emails: list[str] | None,
    source_type: list[DocumentSource] | None,
    title_contains: list[str] | None,
    updated_after: datetime | None,
    updated_before: datetime | None,
    owned_by: list[str] | None,
    parent_hierarchy_node_id: list[int] | None,
    scope: DocumentScope | None,
    ensure_connector_join: bool = False,
) -> Select:
    """Apply the document ACL plus the allowlisted filters.

    The ACL is `apply_document_access_filter`'s, with the granting pairs
    resolved first (`resolve_document_access_pairs`), so the planner sees each
    pair's real size. A document in multiple cc_pairs yields duplicate rows,
    so callers must dedupe (`GROUP BY` / `count(distinct ...)`). `hidden`
    documents are excluded here — admins hid them from search, and this tool
    must not be a bypass.

    Date filters compare against `doc_updated_at` (source-updated time), so
    documents with an unknown source timestamp fall out of any date range.

    Source filtering limits the granting pairs, so a document is attributed to
    a source only when that source's cc_pair grants access. This only diverges
    for a doc id shared across cc_pairs of *different* sources — practically
    nonexistent, since doc ids embed source-specific URLs/ids.
    """
    with _timeouts_as_tool_errors():
        pairs = resolve_document_access_pairs(
            db_session, user_id, _document_source_types(source_type, scope)
        )
    stmt = apply_resolved_document_access_filter(
        db_session,
        stmt,
        pairs,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
    )
    stmt = stmt.where(Document.hidden.is_(False))

    if ensure_connector_join:
        stmt = stmt.join(
            Connector, Connector.id == DocumentByConnectorCredentialPair.connector_id
        )
    if title_contains is not None:
        stmt = stmt.where(_ilike_contains(Document.semantic_id, title_contains))
    if updated_after is not None:
        stmt = stmt.where(Document.doc_updated_at >= updated_after)
    if updated_before is not None:
        stmt = stmt.where(Document.doc_updated_at < updated_before)
    if owned_by is not None:
        stmt = stmt.where(
            Document.primary_owners.overlap(
                cast(postgresql.array(owned_by), postgresql.ARRAY(String))
            )
        )
    if parent_hierarchy_node_id is not None:
        stmt = stmt.where(
            Document.parent_hierarchy_node_id.in_(parent_hierarchy_node_id)
        )
    if scope is not None:
        stmt = stmt.where(_document_scope_filter(scope))
    return stmt


class DocumentPage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rows: list[tuple[Document, DocumentSource]]
    # Set when more documents match after this page.
    next_cursor: DocumentCursor | None


def _order_column(
    order: DocumentOrder,
) -> InstrumentedAttribute[datetime | None] | InstrumentedAttribute[str]:
    if order in (DocumentOrder.UPDATED_DESC, DocumentOrder.UPDATED_ASC):
        return Document.doc_updated_at
    if order in (DocumentOrder.CREATED_DESC, DocumentOrder.CREATED_ASC):
        return Document.doc_created_at
    return Document.semantic_id


def _after_document_cursor(
    cursor: DocumentCursor, order: DocumentOrder
) -> ColumnElement[bool]:
    """Documents after `cursor` in `order`: the ordered column with NULLS
    LAST, then `id` in the same direction."""
    column = _order_column(order)
    descending = order.is_descending
    id_after = (
        Document.id < cursor.document_id
        if descending
        else Document.id > cursor.document_id
    )
    if cursor.sort_value is None:
        return and_(column.is_(None), id_after)
    value_after = (
        column < cursor.sort_value if descending else column > cursor.sort_value
    )
    return or_(
        value_after,
        and_(column == cursor.sort_value, id_after),
        column.is_(None),
    )


def query_documents_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: list[DocumentSource] | None = None,
    title_contains: list[str] | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: list[str] | None = None,
    parent_hierarchy_node_id: list[int] | None = None,
    scope: DocumentScope | None = None,
    order: DocumentOrder = DocumentOrder.UPDATED_DESC,
    after: DocumentCursor | None = None,
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT,
) -> DocumentPage:
    """One page of accessible documents matching the filters, with their
    connector source, in `order`. `after` continues from the previous page's
    `next_cursor`, which must come from the same order. Keyset paging:
    documents indexed between pages cannot shift the pages. A document whose
    ordered value changes between pages moves in the order, so it can be
    skipped or repeated. Only the newest-updated order (and its reverse) can
    read its rows from an index; the other orders sort the matching
    documents."""
    column = _order_column(order)
    # One row per document even when cc_pairs of two sources grant access.
    # The ordered value is selected as a column too: the cursor must not read
    # it from a Document the session loaded earlier.
    stmt = select(Document, func.min(Connector.source), column)
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
        scope=scope,
        ensure_connector_join=True,
    )
    if after is not None:
        stmt = stmt.where(_after_document_cursor(after, order))
    page_size = _clamp_limit(limit)
    if order.is_descending:
        order_by = (column.desc().nulls_last(), Document.id.desc())
    else:
        order_by = (column.asc().nulls_last(), Document.id.asc())
    # One extra row tells whether another page exists.
    stmt = stmt.group_by(Document.id).order_by(*order_by).limit(page_size + 1)
    result = list(_execute_with_timeout(db_session, stmt).tuples().all())
    rows = [(doc, source) for doc, source, _ in result[:page_size]]
    if len(result) <= page_size:
        return DocumentPage(rows=rows, next_cursor=None)
    last_doc, _, last_value = result[page_size - 1]
    return DocumentPage(
        rows=rows,
        next_cursor=DocumentCursor(sort_value=last_value, document_id=last_doc.id),
    )


def _count_documents_stmt(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None,
    prior_emails: list[str] | None,
    source_type: list[DocumentSource] | None,
    title_contains: list[str] | None,
    updated_after: datetime | None,
    updated_before: datetime | None,
    owned_by: list[str] | None,
    parent_hierarchy_node_id: list[int] | None,
    scope: DocumentScope | None,
) -> Select:
    stmt = select(func.count(distinct(Document.id))).select_from(Document)
    return _apply_document_filters(
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
        scope=scope,
    )


def count_documents_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: list[DocumentSource] | None = None,
    title_contains: list[str] | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: list[str] | None = None,
    parent_hierarchy_node_id: list[int] | None = None,
    scope: DocumentScope | None = None,
) -> int:
    """Exact count of accessible documents matching the filters."""
    stmt = _count_documents_stmt(
        db_session,
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
        scope=scope,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def try_count_documents_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: list[DocumentSource] | None = None,
    title_contains: list[str] | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: list[str] | None = None,
    parent_hierarchy_node_id: list[int] | None = None,
    scope: DocumentScope | None = None,
) -> int | None:
    """`count_documents_for_tool` under a short timeout, or None when it runs
    out. A savepoint keeps the session usable after the cancel. The timeout
    also covers the access lookups that build the statement."""
    savepoint = db_session.begin_nested()
    try:
        with _timeouts_as_tool_errors():
            db_session.execute(
                select(
                    func.set_config("statement_timeout", _OPTIONAL_COUNT_TIMEOUT, True)
                )
            )
            stmt = _count_documents_stmt(
                db_session,
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
                scope=scope,
            )
            count = db_session.execute(stmt).scalar_one()
    except PostgresToolQueryTimeoutError:
        savepoint.rollback()
        return None
    # Also ends the savepoint's shorter timeout.
    savepoint.rollback()
    return count


def count_documents_grouped_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    group_by: DocumentGroupBy,
    *,
    user_id: UUID | None = None,
    prior_emails: list[str] | None = None,
    source_type: list[DocumentSource] | None = None,
    title_contains: list[str] | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    owned_by: list[str] | None = None,
    parent_hierarchy_node_id: list[int] | None = None,
    scope: DocumentScope | None = None,
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
        scope=scope,
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
    source_type: list[DocumentSource] | None,
    name_contains: list[str] | None,
    parent_id: list[int] | None,
    node_type: list[HierarchyNodeType] | None,
    scope: DocumentScope | None,
) -> Select:
    # STUB nodes are internal placeholders and never surfaced (existing
    # precedent in hierarchy search).
    stmt = stmt.where(HierarchyNode.node_type != HierarchyNodeType.STUB, access_filter)

    if source_type is not None:
        stmt = stmt.where(HierarchyNode.source.in_(source_type))
    if name_contains is not None:
        stmt = stmt.where(_ilike_contains(HierarchyNode.display_name, name_contains))
    if parent_id is not None:
        stmt = stmt.where(HierarchyNode.parent_id.in_(parent_id))
    if node_type is not None:
        stmt = stmt.where(HierarchyNode.node_type.in_(node_type))
    if scope is not None:
        stmt = stmt.where(_hierarchy_scope_filter(scope))
    return stmt


def _query_hierarchy_nodes(
    db_session: Session,
    access_filter: ColumnElement[bool],
    *,
    source_type: list[DocumentSource] | None = None,
    name_contains: list[str] | None = None,
    parent_id: list[int] | None = None,
    node_type: list[HierarchyNodeType] | None = None,
    scope: DocumentScope | None = None,
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
        scope=scope,
    )
    stmt = stmt.order_by(HierarchyNode.display_name, HierarchyNode.id).limit(
        _clamp_limit(limit)
    )
    return list(_execute_with_timeout(db_session, stmt).scalars().all())


def _count_hierarchy_nodes(
    db_session: Session,
    access_filter: ColumnElement[bool],
    *,
    source_type: list[DocumentSource] | None = None,
    name_contains: list[str] | None = None,
    parent_id: list[int] | None = None,
    node_type: list[HierarchyNodeType] | None = None,
    scope: DocumentScope | None = None,
) -> int:
    stmt = select(func.count()).select_from(HierarchyNode)
    stmt = _apply_hierarchy_node_filters(
        stmt,
        access_filter,
        source_type=source_type,
        name_contains=name_contains,
        parent_id=parent_id,
        node_type=node_type,
        scope=scope,
    )
    return _execute_with_timeout(db_session, stmt).scalar_one()


def query_hierarchy_nodes_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    source_type: list[DocumentSource] | None = None,
    name_contains: list[str] | None = None,
    parent_id: list[int] | None = None,
    node_type: list[HierarchyNodeType] | None = None,
    scope: DocumentScope | None = None,
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
        scope=scope,
        limit=limit,
    )


def count_hierarchy_nodes_for_tool(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    *,
    user_id: UUID | None = None,
    source_type: list[DocumentSource] | None = None,
    name_contains: list[str] | None = None,
    parent_id: list[int] | None = None,
    node_type: list[HierarchyNodeType] | None = None,
    scope: DocumentScope | None = None,
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
        scope=scope,
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
    description_contains: list[str] | None,
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
    description_contains: list[str] | None = None,
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
    description_contains: list[str] | None = None,
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
    description_contains: list[str] | None = None,
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
    chat_session_id: list[UUID] | None,
    content_contains: list[str] | None,
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
        stmt = stmt.where(ChatMessage.chat_session_id.in_(chat_session_id))
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
    chat_session_id: list[UUID] | None = None,
    content_contains: list[str] | None = None,
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
    chat_session_id: list[UUID] | None = None,
    content_contains: list[str] | None = None,
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
    chat_session_id: list[UUID] | None = None,
    content_contains: list[str] | None = None,
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
