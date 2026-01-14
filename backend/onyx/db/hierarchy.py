"""CRUD operations for HierarchyNode."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import HierarchyNode
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def resolve_parent_hierarchy_node_id(
    db_session: Session,
    raw_parent_id: str | None,
    source: DocumentSource,
) -> int | None:
    """
    Resolve a raw_parent_id to a database HierarchyNode ID.

    If raw_parent_id is None, returns the SOURCE node ID for backward compatibility.
    If the parent node doesn't exist, returns the SOURCE node ID as fallback.
    """
    if raw_parent_id is None:
        # No parent specified - use the SOURCE node
        source_node = get_source_hierarchy_node(db_session, source)
        return source_node.id if source_node else None

    parent_node = get_hierarchy_node_by_raw_id(db_session, raw_parent_id, source)
    if parent_node:
        return parent_node.id

    # Parent not found - fall back to SOURCE node
    logger.warning(
        f"Parent hierarchy node not found: raw_id={raw_parent_id}, source={source}. "
        "Falling back to SOURCE node."
    )
    source_node = get_source_hierarchy_node(db_session, source)
    return source_node.id if source_node else None


def upsert_hierarchy_node(
    db_session: Session,
    node: PydanticHierarchyNode,
    source: DocumentSource,
    commit: bool = True,
) -> HierarchyNode:
    """
    Upsert a hierarchy node from a Pydantic model.

    Uses PostgreSQL ON CONFLICT to handle upserts efficiently.
    """
    # Resolve parent_id from raw_parent_id
    parent_id = resolve_parent_hierarchy_node_id(db_session, node.raw_parent_id, source)

    values = {
        "raw_node_id": node.raw_node_id,
        "display_name": node.display_name,
        "link": node.link,
        "source": source.value,
        "node_type": node.node_type.value,
        "document_id": node.document_id,
        "parent_id": parent_id,
    }

    stmt = insert(HierarchyNode).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_hierarchy_node_raw_id_source",
        set_={
            "display_name": stmt.excluded.display_name,
            "link": stmt.excluded.link,
            "node_type": stmt.excluded.node_type,
            "document_id": stmt.excluded.document_id,
            "parent_id": stmt.excluded.parent_id,
        },
    )
    stmt = stmt.returning(HierarchyNode)
    result = db_session.execute(stmt)
    hierarchy_node = result.scalar_one()

    if commit:
        db_session.commit()

    return hierarchy_node


def upsert_hierarchy_nodes_batch(
    db_session: Session,
    nodes: list[PydanticHierarchyNode],
    source: DocumentSource,
    commit: bool = True,
) -> list[HierarchyNode]:
    """
    Batch upsert hierarchy nodes.

    Note: This function processes nodes in order. For correct parent resolution,
    parent nodes should appear before their children in the list.
    """
    results = []
    for node in nodes:
        hierarchy_node = upsert_hierarchy_node(db_session, node, source, commit=False)
        results.append(hierarchy_node)

    if commit:
        db_session.commit()

    return results


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
