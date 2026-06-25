"""CRUD operations for HierarchyNode."""

from collections import defaultdict

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import Document
from onyx.db.models import HierarchyNode
from onyx.db.models import HierarchyNodeByConnectorCredentialPair
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()

# Sources where hierarchy nodes can also be documents.
# For these sources, pages/items can be both a hierarchy node (with children)
# AND a document with indexed content. For example:
# - Notion: Pages with child pages are hierarchy nodes, but also documents
# - Confluence: Pages can have child pages and also contain content
# Other sources like Google Drive have folders as hierarchy nodes, but folders
# are not documents themselves.
SOURCES_WITH_HIERARCHY_NODE_DOCUMENTS: set[DocumentSource] = {
    DocumentSource.NOTION,
    DocumentSource.CONFLUENCE,
}


def _get_source_display_name(source: DocumentSource) -> str:
    """Get a human-readable display name for a source type."""
    return source.value.replace("_", " ").title()


def get_hierarchy_node_by_raw_id(
    db_session: Session,
    raw_node_id: str,
    source: DocumentSource,
) -> HierarchyNode | None:
    """Get a hierarchy node by its raw ID and source."""
    stmt = select(HierarchyNode).where(
        HierarchyNode.raw_node_id == raw_node_id,
        HierarchyNode.source == source,
    )
    return db_session.execute(stmt).scalar_one_or_none()


def get_source_hierarchy_node(
    db_session: Session,
    source: DocumentSource,
) -> HierarchyNode | None:
    """Get the SOURCE-type root node for a given source."""
    stmt = select(HierarchyNode).where(
        HierarchyNode.source == source,
        HierarchyNode.node_type == HierarchyNodeType.SOURCE,
    )
    return db_session.execute(stmt).scalar_one_or_none()


def ensure_source_node_exists(
    db_session: Session,
    source: DocumentSource,
    commit: bool = True,
) -> HierarchyNode:
    """
    Ensure that a SOURCE-type root node exists for the given source.

    This function is idempotent - it will return the existing SOURCE node if one
    exists, or create a new one if not.

    The SOURCE node is the root of the hierarchy tree for a given source type
    (e.g., "Google Drive", "Confluence"). All other hierarchy nodes for that
    source should ultimately have this node as an ancestor.

    For the SOURCE node:
    - raw_node_id is set to the source name (e.g., "google_drive")
    - parent_id is None (it's the root)
    - display_name is a human-readable version (e.g., "Google Drive")

    Args:
        db_session: SQLAlchemy session
        source: The document source type
        commit: Whether to commit the transaction

    Returns:
        The existing or newly created SOURCE-type HierarchyNode
    """
    # Try to get existing SOURCE node first
    existing_node = get_source_hierarchy_node(db_session, source)
    if existing_node:
        return existing_node

    # Create the SOURCE node
    display_name = _get_source_display_name(source)

    source_node = HierarchyNode(
        raw_node_id=source.value,  # Use source name as raw_node_id
        display_name=display_name,
        link=None,
        source=source,
        node_type=HierarchyNodeType.SOURCE,
        document_id=None,
        parent_id=None,  # SOURCE nodes have no parent
    )

    db_session.add(source_node)

    # Flush to get the ID and detect any race conditions
    try:
        db_session.flush()
    except Exception:
        # Race condition - another worker created it. Roll back and fetch.
        db_session.rollback()
        existing_node = get_source_hierarchy_node(db_session, source)
        if existing_node:
            return existing_node
        # If still not found, re-raise the original exception
        raise

    if commit:
        db_session.commit()

    logger.info(
        "Created SOURCE hierarchy node for %s: id=%s, display_name=%s",
        source.value,
        source_node.id,
        display_name,
    )

    return source_node


def _create_stub_hierarchy_node(
    db_session: Session,
    raw_node_id: str,
    source: DocumentSource,
    source_node_id: int,
) -> HierarchyNode:
    """Create a STUB placeholder for a parent that hasn't been indexed yet.

    Flushed immediately so subsequent lookups in the same session find it,
    preventing duplicate stubs when multiple children share the same missing parent.
    The stub is promoted to the real node type when the parent page is processed.
    """
    stub = HierarchyNode(
        raw_node_id=raw_node_id,
        display_name="__stub__",
        link=None,
        source=source,
        node_type=HierarchyNodeType.STUB,
        parent_id=source_node_id,
        is_public=False,
    )
    db_session.add(stub)
    try:
        with db_session.begin_nested():
            db_session.flush()
        return stub
    except IntegrityError:
        # A concurrent worker inserted this stub first; return theirs.
        existing = get_hierarchy_node_by_raw_id(db_session, raw_node_id, source)
        if existing is not None:
            return existing
        raise


def upsert_parents(
    db_session: Session,
    node: PydanticHierarchyNode,
    source_node_id: int,
    source: DocumentSource,
    node_by_id: dict[str, PydanticHierarchyNode],
    done_ids: set[str],
    is_connector_public: bool = False,
) -> list[HierarchyNode]:
    """
    Upsert the in-batch ancestors of ``node`` in oldest-to-newest order.

    Walks ``raw_parent_id`` links iteratively (not recursively) so deeply nested
    hierarchies — Notion page chains can exceed Python's recursion limit — and
    cyclic parent references do not raise ``RecursionError``.
    """
    # Walk ancestors, newest-first, collecting any that still need upserting.
    # ``visiting`` seeded with ``node`` so a self-parent (A -> A) is treated as
    # a cycle, not appended to ``pending``.
    pending: list[PydanticHierarchyNode] = []
    visiting: set[str] = {node.raw_node_id}
    current = node
    while True:
        parent_raw_id = current.raw_parent_id
        if (
            current.node_type == HierarchyNodeType.SOURCE
            or parent_raw_id is None
            or parent_raw_id not in node_by_id
            or parent_raw_id in done_ids
        ):
            break
        if parent_raw_id in visiting:
            # Cycle in the parent chain (e.g. A -> B -> A or A -> A). Stop
            # walking.
            logger.warning(
                "Cycle detected in hierarchy parent chain for source=%s "
                "at raw_node_id=%s (raw_parent_id=%s); falling back to SOURCE "
                "for the cyclic ancestors.",
                source,
                current.raw_node_id,
                parent_raw_id,
            )
            break
        parent_node = node_by_id[parent_raw_id]
        pending.append(parent_node)
        visiting.add(parent_raw_id)
        current = parent_node

    # Drain oldest-first so each parent is persisted before its children.
    created: list[HierarchyNode] = []
    for parent_node in reversed(pending):
        created.extend(
            upsert_hierarchy_node(
                db_session,
                parent_node,
                source_node_id,
                source,
                commit=False,
                is_connector_public=is_connector_public,
            )
        )
        done_ids.add(parent_node.raw_node_id)
    return created


def upsert_hierarchy_node(
    db_session: Session,
    node: PydanticHierarchyNode,
    source_node_id: int,
    source: DocumentSource,
    commit: bool = True,
    is_connector_public: bool = False,
) -> list[HierarchyNode]:
    """
    Upsert a hierarchy node from a Pydantic model.

    If a node with the same raw_node_id and source exists, updates it.
    Otherwise, creates a new node.

    Returns a list containing the upserted node, plus a STUB node if one was
    created for a missing parent. The STUB is promoted when the real parent is
    later processed.

    Args:
        db_session: SQLAlchemy session
        node: The Pydantic hierarchy node to upsert
        source: Document source type
        commit: Whether to commit the transaction
        is_connector_public: If True, the connector is public (organization-wide access)
            and all hierarchy nodes should be marked as public regardless of their
            external_access settings. This ensures nodes from public connectors are
            accessible to all users.
        source_node_id: DB id of the SOURCE root node for this source, used to
            detect and replace the fallback with a STUB for missing cross-batch parents.
    """
    ret: list[HierarchyNode] = []
    if node.node_type == HierarchyNodeType.SOURCE:
        parent_id: int | None = None
    elif node.raw_parent_id is None:
        parent_id = source_node_id
    else:
        parent_node = get_hierarchy_node_by_raw_id(
            db_session, node.raw_parent_id, source
        )
        if parent_node is not None:
            parent_id = parent_node.id
        else:
            stub = _create_stub_hierarchy_node(
                db_session, node.raw_parent_id, source, source_node_id
            )
            parent_id = stub.id
            ret.append(stub)

    # For public connectors, all nodes are public
    # Otherwise, extract permission fields from external_access if present
    if is_connector_public:
        is_public = True
        external_user_emails: list[str] | None = None
        external_user_group_ids: list[str] | None = None
    elif node.external_access:
        is_public = node.external_access.is_public
        external_user_emails = (
            list(node.external_access.external_user_emails)
            if node.external_access.external_user_emails
            else None
        )
        external_user_group_ids = (
            list(node.external_access.external_user_group_ids)
            if node.external_access.external_user_group_ids
            else None
        )
    else:
        is_public = False
        external_user_emails = None
        external_user_group_ids = None

    # Check if node already exists
    existing_node = get_hierarchy_node_by_raw_id(db_session, node.raw_node_id, source)

    if existing_node:
        # Update existing node
        existing_node.display_name = node.display_name
        existing_node.link = node.link
        existing_node.node_type = node.node_type
        existing_node.parent_id = parent_id
        # Update permission fields
        existing_node.is_public = is_public
        existing_node.external_user_emails = external_user_emails
        existing_node.external_user_group_ids = external_user_group_ids
        hierarchy_node = existing_node
    else:
        # Create new node
        hierarchy_node = HierarchyNode(
            raw_node_id=node.raw_node_id,
            display_name=node.display_name,
            link=node.link,
            source=source,
            node_type=node.node_type,
            parent_id=parent_id,
            is_public=is_public,
            external_user_emails=external_user_emails,
            external_user_group_ids=external_user_group_ids,
        )
        db_session.add(hierarchy_node)
    ret.append(hierarchy_node)

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return ret


def upsert_hierarchy_nodes_batch(
    db_session: Session,
    nodes: list[PydanticHierarchyNode],
    source: DocumentSource,
    commit: bool = True,
    is_connector_public: bool = False,
) -> list[HierarchyNode]:
    """
    Batch upsert hierarchy nodes.

    Handles parent dependencies automatically: in-batch ancestors are upserted
    before their children, and cross-batch missing parents get a STUB placeholder
    that is promoted when the real parent is later processed.

    Returns all upserted nodes including any STUB nodes created for missing parents,
    so callers can cache and register them all uniformly.

    Args:
        db_session: SQLAlchemy session
        nodes: List of Pydantic hierarchy nodes to upsert
        source: Document source type
        commit: Whether to commit the transaction
        is_connector_public: If True, the connector is public (organization-wide access)
            and all hierarchy nodes should be marked as public regardless of their
            external_access settings.
    """
    source_node = ensure_source_node_exists(db_session, source)
    source_node_id = source_node.id

    node_by_id = {}
    for node in nodes:
        if node.node_type != HierarchyNodeType.SOURCE:
            node_by_id[node.raw_node_id] = node
    done_ids: set[str] = set()

    all_nodes: list[HierarchyNode] = []
    for node in nodes:
        if node.raw_node_id in done_ids:
            continue
        all_nodes.extend(
            upsert_parents(
                db_session,
                node,
                source_node_id,
                source,
                node_by_id,
                done_ids,
                is_connector_public=is_connector_public,
            )
        )
        all_nodes.extend(
            upsert_hierarchy_node(
                db_session,
                node,
                source_node_id,
                source,
                commit=False,
                is_connector_public=is_connector_public,
            )
        )
        done_ids.add(node.raw_node_id)

    if commit:
        db_session.commit()

    return all_nodes


def link_hierarchy_nodes_to_documents(
    db_session: Session,
    document_ids: list[str],
    source: DocumentSource,
    commit: bool = True,
) -> int:
    """
    Link hierarchy nodes to their corresponding documents.

    For connectors like Notion and Confluence where pages can be both hierarchy nodes
    AND documents, we need to set the document_id field on hierarchy nodes after the
    documents are created. This is because hierarchy nodes are processed before documents,
    and the FK constraint on document_id requires the document to exist first.

    Args:
        db_session: SQLAlchemy session
        document_ids: List of document IDs that were just created/updated
        source: The document source (e.g., NOTION, CONFLUENCE)
        commit: Whether to commit the transaction

    Returns:
        Number of hierarchy nodes that were linked to documents
    """
    # Skip for sources where hierarchy nodes cannot also be documents
    if source not in SOURCES_WITH_HIERARCHY_NODE_DOCUMENTS:
        return 0

    if not document_ids:
        return 0

    # Find hierarchy nodes where raw_node_id matches a document_id
    # These are pages that are both hierarchy nodes and documents
    stmt = select(HierarchyNode).where(
        HierarchyNode.source == source,
        HierarchyNode.raw_node_id.in_(document_ids),
        HierarchyNode.document_id.is_(None),  # Only update if not already linked
    )
    nodes_to_update = list(db_session.execute(stmt).scalars().all())

    # Update document_id for each matching node
    for node in nodes_to_update:
        node.document_id = node.raw_node_id

    if commit:
        db_session.commit()

    if nodes_to_update:
        logger.debug(
            "Linked %s hierarchy nodes to documents for source %s",
            len(nodes_to_update),
            source.value,
        )

    return len(nodes_to_update)


def get_hierarchy_node_children(
    db_session: Session,
    parent_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[HierarchyNode]:
    """Get children of a hierarchy node, paginated."""
    stmt = (
        select(HierarchyNode)
        .where(HierarchyNode.parent_id == parent_id)
        .order_by(HierarchyNode.display_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db_session.execute(stmt).scalars().all())


def get_hierarchy_node_by_id(
    db_session: Session,
    node_id: int,
) -> HierarchyNode | None:
    """Get a hierarchy node by its database ID."""
    return db_session.get(HierarchyNode, node_id)


def get_root_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
) -> list[HierarchyNode]:
    """Get all root-level hierarchy nodes for a source (children of SOURCE node)."""
    source_node = get_source_hierarchy_node(db_session, source)
    if not source_node:
        return []

    return get_hierarchy_node_children(db_session, source_node.id)


def get_all_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
) -> list[HierarchyNode]:
    """
    Get ALL hierarchy nodes for a given source.

    This is used to populate the Redis cache. Returns all nodes including
    the SOURCE-type root node.

    Args:
        db_session: SQLAlchemy session
        source: The document source to get nodes for

    Returns:
        List of all HierarchyNode objects for the source
    """
    stmt = select(HierarchyNode).where(HierarchyNode.source == source)
    return list(db_session.execute(stmt).scalars().all())


def _get_accessible_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
    user_email: str,  # noqa: ARG001
    external_group_ids: list[str],  # noqa: ARG001
) -> list[HierarchyNode]:
    """
    MIT version: Returns all hierarchy nodes for the source without permission filtering.

    In the MIT version, permission checks are not performed on hierarchy nodes.
    The EE version overrides this to apply permission filtering based on user
    email and external group IDs.

    Args:
        db_session: SQLAlchemy session
        source: Document source type
        user_email: User's email (unused in MIT version)
        external_group_ids: User's external group IDs (unused in MIT version)

    Returns:
        List of all HierarchyNode objects for the source
    """
    stmt = select(HierarchyNode).where(
        HierarchyNode.source == source,
        HierarchyNode.node_type != HierarchyNodeType.STUB,
    )
    stmt = stmt.order_by(HierarchyNode.display_name)
    return list(db_session.execute(stmt).scalars().all())


def get_accessible_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
    user_email: str,
    external_group_ids: list[str],
) -> list[HierarchyNode]:
    """
    Get hierarchy nodes for a source that are accessible to the user.

    Uses fetch_versioned_implementation to get the appropriate version:
    - MIT version: Returns all nodes (no permission filtering)
    - EE version: Filters based on user email and external group IDs
    """
    versioned_fn = fetch_versioned_implementation(
        "onyx.db.hierarchy", "_get_accessible_hierarchy_nodes_for_source"
    )
    return versioned_fn(db_session, source, user_email, external_group_ids)


HIERARCHY_NODE_SEARCH_LIMIT = 30


def escape_like_pattern(s: str) -> str:
    """Escape LIKE metacharacters so user input is treated as a literal substring."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_accessible_hierarchy_nodes(
    db_session: Session,
    query: str,
    sources: list[DocumentSource] | None,
    user_email: str,  # noqa: ARG001
    external_group_ids: list[str],  # noqa: ARG001
    limit: int = HIERARCHY_NODE_SEARCH_LIMIT,
) -> list[HierarchyNode]:
    """MIT version: case-insensitive display_name search without ACL filtering."""
    pattern = f"%{escape_like_pattern(query)}%"
    stmt = (
        select(HierarchyNode)
        .where(
            HierarchyNode.node_type.notin_(
                [HierarchyNodeType.STUB, HierarchyNodeType.SOURCE]
            ),
            HierarchyNode.display_name.ilike(pattern, escape="\\"),
        )
        .order_by(HierarchyNode.display_name)
        .limit(limit)
    )
    if sources:
        stmt = stmt.where(HierarchyNode.source.in_(sources))
    return list(db_session.execute(stmt).scalars().all())


def search_accessible_hierarchy_nodes(
    db_session: Session,
    query: str,
    sources: list[DocumentSource] | None,
    user_email: str,
    external_group_ids: list[str],
    limit: int = HIERARCHY_NODE_SEARCH_LIMIT,
) -> list[HierarchyNode]:
    """Search hierarchy nodes by display_name substring, ACL-gated.

    MIT version returns all matching nodes; EE version applies permission filtering.
    STUB and SOURCE nodes are always excluded.
    """
    versioned_fn = fetch_versioned_implementation(
        "onyx.db.hierarchy", "_search_accessible_hierarchy_nodes"
    )
    return versioned_fn(
        db_session, query, sources, user_email, external_group_ids, limit
    )


def _filter_accessible_hierarchy_node_ids(
    db_session: Session,  # noqa: ARG001
    node_ids: list[int],
    user_email: str,  # noqa: ARG001
    external_group_ids: list[str],  # noqa: ARG001
) -> set[int]:
    """MIT version: hierarchy nodes carry no permission filtering — all
    requested ids pass. The EE version applies the access filter."""
    return set(node_ids)


def filter_accessible_hierarchy_node_ids(
    db_session: Session,
    node_ids: list[int],
    user_email: str,
    external_group_ids: list[str],
) -> set[int]:
    """Return the subset of ``node_ids`` the user can access (EE filters,
    MIT passes everything through)."""
    if not node_ids:
        return set()
    versioned_fn = fetch_versioned_implementation(
        "onyx.db.hierarchy", "_filter_accessible_hierarchy_node_ids"
    )
    return versioned_fn(db_session, node_ids, user_email, external_group_ids)


def get_document_parent_hierarchy_node_ids(
    db_session: Session,
    document_ids: list[str],
) -> dict[str, int | None]:
    """
    Get the parent_hierarchy_node_id for multiple documents in a single query.

    Args:
        db_session: SQLAlchemy session
        document_ids: List of document IDs to look up

    Returns:
        Dict mapping document_id -> parent_hierarchy_node_id (or None if not set)
    """

    if not document_ids:
        return {}

    stmt = select(Document.id, Document.parent_hierarchy_node_id).where(
        Document.id.in_(document_ids)
    )
    results = db_session.execute(stmt).all()

    return {doc_id: parent_id for doc_id, parent_id in results}


def update_document_parent_hierarchy_nodes(
    db_session: Session,
    doc_parent_map: dict[str, int | None],
    commit: bool = True,
) -> int:
    """Bulk-update Document.parent_hierarchy_node_id for multiple documents.

    Only updates rows whose current value differs from the desired value to
    avoid unnecessary writes.

    Args:
        db_session: SQLAlchemy session
        doc_parent_map: Mapping of document_id → desired parent_hierarchy_node_id
        commit: Whether to commit the transaction

    Returns:
        Number of documents actually updated
    """
    if not doc_parent_map:
        return 0

    doc_ids = list(doc_parent_map.keys())
    existing = get_document_parent_hierarchy_node_ids(db_session, doc_ids)

    by_parent: dict[int | None, list[str]] = defaultdict(list)
    for doc_id, desired_parent_id in doc_parent_map.items():
        current = existing.get(doc_id)
        if current == desired_parent_id or doc_id not in existing:
            continue
        by_parent[desired_parent_id].append(doc_id)

    updated = 0
    for desired_parent_id, ids in by_parent.items():
        db_session.query(Document).filter(Document.id.in_(ids)).update(
            {Document.parent_hierarchy_node_id: desired_parent_id},
            synchronize_session=False,
        )
        updated += len(ids)

    if commit:
        db_session.commit()
    elif updated:
        db_session.flush()

    return updated


def update_hierarchy_node_permissions(
    db_session: Session,
    raw_node_id: str,
    source: DocumentSource,
    is_public: bool,
    external_user_emails: list[str] | None,
    external_user_group_ids: list[str] | None,
    commit: bool = True,
) -> bool:
    """
    Update permissions for an existing hierarchy node.

    This is used during permission sync to update folder permissions
    without needing the full Pydantic HierarchyNode model.

    Args:
        db_session: SQLAlchemy session
        raw_node_id: Raw node ID from the source system
        source: Document source type
        is_public: Whether the node is public
        external_user_emails: List of user emails with access
        external_user_group_ids: List of group IDs with access
        commit: Whether to commit the transaction

    Returns:
        True if the node was found and updated, False if not found
    """
    existing_node = get_hierarchy_node_by_raw_id(db_session, raw_node_id, source)

    if not existing_node:
        logger.warning(
            "Hierarchy node not found for permission update: raw_node_id=%s, source=%s",
            raw_node_id,
            source,
        )
        return False

    existing_node.is_public = is_public
    existing_node.external_user_emails = external_user_emails
    existing_node.external_user_group_ids = external_user_group_ids

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return True


def upsert_hierarchy_node_cc_pair_entries(
    db_session: Session,
    hierarchy_node_ids: list[int],
    connector_id: int,
    credential_id: int,
    commit: bool = True,
) -> None:
    """Insert rows into HierarchyNodeByConnectorCredentialPair, ignoring conflicts.

    This records that the given cc_pair "owns" these hierarchy nodes. Used by
    indexing, pruning, and hierarchy-fetching paths.
    """
    if not hierarchy_node_ids:
        return

    _M = HierarchyNodeByConnectorCredentialPair
    stmt = pg_insert(_M).values(
        [
            {
                _M.hierarchy_node_id: node_id,
                _M.connector_id: connector_id,
                _M.credential_id: credential_id,
            }
            for node_id in hierarchy_node_ids
        ]
    )
    stmt = stmt.on_conflict_do_nothing()
    db_session.execute(stmt)

    if commit:
        db_session.commit()
    else:
        db_session.flush()


def remove_stale_hierarchy_node_cc_pair_entries(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    live_hierarchy_node_ids: set[int],
    commit: bool = True,
) -> int:
    """Delete join-table rows for this cc_pair that are NOT in the live set.

    If ``live_hierarchy_node_ids`` is empty ALL rows for the cc_pair are deleted
    (i.e. the connector no longer has any hierarchy nodes). Callers that want a
    no-op when there are no live nodes must guard before calling.

    Returns the number of deleted rows.
    """
    stmt = delete(HierarchyNodeByConnectorCredentialPair).where(
        HierarchyNodeByConnectorCredentialPair.connector_id == connector_id,
        HierarchyNodeByConnectorCredentialPair.credential_id == credential_id,
    )
    if live_hierarchy_node_ids:
        stmt = stmt.where(
            HierarchyNodeByConnectorCredentialPair.hierarchy_node_id.notin_(
                live_hierarchy_node_ids
            )
        )

    result: CursorResult = db_session.execute(stmt)  # ty: ignore[invalid-assignment]
    deleted = result.rowcount

    if commit:
        db_session.commit()
    elif deleted:
        db_session.flush()

    return deleted


def delete_orphaned_hierarchy_nodes(
    db_session: Session,
    source: DocumentSource,
    commit: bool = True,
) -> list[str]:
    """Delete hierarchy nodes for a source that have zero cc_pair associations.

    SOURCE-type nodes are excluded (they are synthetic roots).

    Returns the list of raw_node_ids that were deleted (for cache eviction).
    """
    # Find orphaned nodes: no rows in the join table
    orphan_stmt = (
        select(HierarchyNode.id, HierarchyNode.raw_node_id)
        .outerjoin(
            HierarchyNodeByConnectorCredentialPair,
            HierarchyNode.id
            == HierarchyNodeByConnectorCredentialPair.hierarchy_node_id,
        )
        .where(
            HierarchyNode.source == source,
            HierarchyNode.node_type != HierarchyNodeType.SOURCE,
            HierarchyNodeByConnectorCredentialPair.hierarchy_node_id.is_(None),
        )
    )
    orphans = db_session.execute(orphan_stmt).all()
    if not orphans:
        return []

    orphan_ids = [row[0] for row in orphans]
    deleted_raw_ids = [row[1] for row in orphans]

    db_session.execute(delete(HierarchyNode).where(HierarchyNode.id.in_(orphan_ids)))

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return deleted_raw_ids


def reparent_orphaned_hierarchy_nodes(
    db_session: Session,
    source: DocumentSource,
    commit: bool = True,
) -> list[HierarchyNode]:
    """Re-parent hierarchy nodes whose parent_id is NULL to the SOURCE node.

    After pruning deletes stale nodes, their former children get parent_id=NULL
    via the SET NULL cascade. This function points them back to the SOURCE root.

    Returns the reparented HierarchyNode objects (with updated parent_id)
    so callers can refresh downstream caches.
    """
    source_node = get_source_hierarchy_node(db_session, source)
    if not source_node:
        return []

    stmt = select(HierarchyNode).where(
        HierarchyNode.source == source,
        HierarchyNode.parent_id.is_(None),
        HierarchyNode.node_type != HierarchyNodeType.SOURCE,
    )
    orphans = list(db_session.execute(stmt).scalars().all())
    if not orphans:
        return []

    for node in orphans:
        node.parent_id = source_node.id

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return orphans
