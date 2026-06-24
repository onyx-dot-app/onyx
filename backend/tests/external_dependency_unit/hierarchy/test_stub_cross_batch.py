"""Tests for STUB hierarchy node creation when a child is indexed before its parent.

During Notion full syncs the search API returns pages in arbitrary order.
When a child page lands in batch N and its parent in batch N+K, the child's
hierarchy node must point to a STUB placeholder rather than SOURCE. The stub
is promoted (display_name, node_type, parent_id all updated) when the real
parent page is later processed, and the child's FK stays correct throughout.
"""

from typing import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import ensure_source_node_exists
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.hierarchy import get_source_hierarchy_node
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch


@pytest.fixture()
def notion_source_node(db_session: Session) -> Generator[None, None, None]:
    ensure_source_node_exists(db_session, DocumentSource.NOTION, commit=False)
    db_session.flush()
    yield
    db_session.rollback()


@pytest.mark.usefixtures("notion_source_node")
def test_child_before_parent_creates_stub_then_promotes(db_session: Session) -> None:
    """Child in batch 1 gets a STUB parent; real parent in batch 2 promotes it."""
    tag = uuid4().hex[:8]
    child_id = f"child_{tag}"
    parent_id = f"parent_{tag}"

    source_node = get_source_hierarchy_node(db_session, DocumentSource.NOTION)
    assert source_node is not None

    # Batch 1: child only — parent doesn't exist yet.
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=child_id,
                raw_parent_id=parent_id,
                display_name="Child",
                node_type=HierarchyNodeType.PAGE,
            )
        ],
        DocumentSource.NOTION,
        commit=False,
    )

    child = get_hierarchy_node_by_raw_id(db_session, child_id, DocumentSource.NOTION)
    stub = get_hierarchy_node_by_raw_id(db_session, parent_id, DocumentSource.NOTION)

    assert child is not None
    assert stub is not None
    assert stub.node_type == HierarchyNodeType.STUB
    assert stub.display_name == "__stub__"
    # Child points to stub, not SOURCE.
    assert child.parent_id == stub.id
    assert child.parent_id != source_node.id

    stub_db_id = stub.id  # must remain unchanged after promotion

    # Batch 2: real parent page arrives.
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=parent_id,
                raw_parent_id=None,
                display_name="Real Parent",
                node_type=HierarchyNodeType.PAGE,
            )
        ],
        DocumentSource.NOTION,
        commit=False,
    )

    # Stub is promoted in-place — same DB id, real fields now.
    promoted = get_hierarchy_node_by_raw_id(
        db_session, parent_id, DocumentSource.NOTION
    )
    assert promoted is not None
    assert promoted.id == stub_db_id
    assert promoted.node_type == HierarchyNodeType.PAGE
    assert promoted.display_name == "Real Parent"
    assert promoted.parent_id == source_node.id

    # Child's FK is unchanged — it still points to the promoted node.
    child_after = get_hierarchy_node_by_raw_id(
        db_session, child_id, DocumentSource.NOTION
    )
    assert child_after is not None
    assert child_after.parent_id == stub_db_id


@pytest.mark.usefixtures("notion_source_node")
def test_stub_promoted_alongside_new_child_in_same_batch(db_session: Session) -> None:
    """Real parent and a new child arrive together in the same batch as the promotion.

    A strict within-call stub-then-promotion can't occur because node_by_id covers
    all non-SOURCE nodes in the batch, so upsert_parents processes the real node
    before any child would trigger stub creation.  This test covers the realistic
    cross-call variant: stub created in batch 1, then batch 2 contains both the real
    parent and a new child that hasn't been seen before.
    """
    tag = uuid4().hex[:8]
    child1_id = f"child1_{tag}"
    child2_id = f"child2_{tag}"
    parent_id = f"parent_{tag}"

    source_node = get_source_hierarchy_node(db_session, DocumentSource.NOTION)
    assert source_node is not None

    # Batch 1: child1 only — parent doesn't exist, stub created.
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=child1_id,
                raw_parent_id=parent_id,
                display_name="Child 1",
                node_type=HierarchyNodeType.PAGE,
            )
        ],
        DocumentSource.NOTION,
        commit=False,
    )

    stub = get_hierarchy_node_by_raw_id(db_session, parent_id, DocumentSource.NOTION)
    assert stub is not None
    assert stub.node_type == HierarchyNodeType.STUB
    stub_db_id = stub.id

    # Batch 2: real parent + a brand-new child2, both arrive together.
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=child2_id,
                raw_parent_id=parent_id,
                display_name="Child 2",
                node_type=HierarchyNodeType.PAGE,
            ),
            PydanticHierarchyNode(
                raw_node_id=parent_id,
                raw_parent_id=None,
                display_name="Real Parent",
                node_type=HierarchyNodeType.PAGE,
            ),
        ],
        DocumentSource.NOTION,
        commit=False,
    )

    promoted = get_hierarchy_node_by_raw_id(
        db_session, parent_id, DocumentSource.NOTION
    )
    assert promoted is not None
    assert promoted.id == stub_db_id
    assert promoted.node_type == HierarchyNodeType.PAGE
    assert promoted.display_name == "Real Parent"

    # Both children point to the promoted parent.
    child1 = get_hierarchy_node_by_raw_id(db_session, child1_id, DocumentSource.NOTION)
    child2 = get_hierarchy_node_by_raw_id(db_session, child2_id, DocumentSource.NOTION)
    assert child1 is not None and child1.parent_id == stub_db_id
    assert child2 is not None and child2.parent_id == stub_db_id


@pytest.mark.usefixtures("notion_source_node")
def test_multiple_children_same_missing_parent_creates_one_stub(
    db_session: Session,
) -> None:
    """Multiple children in the same batch pointing to the same missing parent
    produce exactly one STUB, not one per child."""
    tag = uuid4().hex[:8]
    parent_id = f"parent_{tag}"
    child_ids = [f"child_{tag}_{i}" for i in range(3)]

    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=cid,
                raw_parent_id=parent_id,
                display_name=f"Child {i}",
                node_type=HierarchyNodeType.PAGE,
            )
            for i, cid in enumerate(child_ids)
        ],
        DocumentSource.NOTION,
        commit=False,
    )

    stub = get_hierarchy_node_by_raw_id(db_session, parent_id, DocumentSource.NOTION)
    assert stub is not None
    assert stub.node_type == HierarchyNodeType.STUB

    # Every child must point to the same stub, not SOURCE.
    source_node = get_source_hierarchy_node(db_session, DocumentSource.NOTION)
    assert source_node is not None
    for cid in child_ids:
        child = get_hierarchy_node_by_raw_id(db_session, cid, DocumentSource.NOTION)
        assert child is not None
        assert child.parent_id == stub.id
        assert child.parent_id != source_node.id
