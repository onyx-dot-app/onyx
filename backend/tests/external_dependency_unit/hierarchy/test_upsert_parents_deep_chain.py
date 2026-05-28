"""Regression tests for `upsert_parents` recursion safety.

Deeply nested Notion workspaces produced parent chains longer than Python's
default recursion limit, causing ``upsert_parents`` to raise ``RecursionError``.
These tests lock in the iterative implementation: a deep chain must complete,
and a cyclic parent reference must not loop or crash.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import ensure_source_node_exists
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch
from onyx.db.models import HierarchyNode

# Notion can produce parent chains exceeding Python's default recursion limit
# (sys.setrecursionlimit() defaults to 1000). 1500 is comfortably past that
# while keeping the test fast.
DEEP_CHAIN_DEPTH = 1500


@pytest.fixture()
def notion_source_node(
    db_session: Session,
) -> Generator[HierarchyNode, None, None]:
    """Ensure the NOTION SOURCE node exists for the duration of the test."""
    source_node = ensure_source_node_exists(
        db_session, DocumentSource.NOTION, commit=False
    )
    db_session.flush()
    yield source_node
    db_session.rollback()


@pytest.mark.usefixtures("notion_source_node")
def test_upsert_parents_handles_deep_chain(
    db_session: Session,
) -> None:
    """A 1500-deep parent chain must upsert without RecursionError."""
    tag = uuid4().hex[:8]
    # Build chain: root -> n1 -> n2 -> ... -> n{DEPTH-1}
    nodes: list[PydanticHierarchyNode] = []
    for i in range(DEEP_CHAIN_DEPTH):
        nodes.append(
            PydanticHierarchyNode(
                raw_node_id=f"deep_{tag}_{i}",
                raw_parent_id=f"deep_{tag}_{i - 1}" if i > 0 else None,
                display_name=f"Deep {i}",
                node_type=HierarchyNodeType.PAGE,
            )
        )

    # Pass the deepest child first so upsert_parents has to walk the entire
    # chain in one call (this is the worst-case shape that originally blew the
    # stack).
    upsert_hierarchy_nodes_batch(
        db_session,
        list(reversed(nodes)),
        DocumentSource.NOTION,
        commit=False,
    )

    # Spot-check head, middle, tail.
    head = get_hierarchy_node_by_raw_id(
        db_session, f"deep_{tag}_0", DocumentSource.NOTION
    )
    middle = get_hierarchy_node_by_raw_id(
        db_session, f"deep_{tag}_{DEEP_CHAIN_DEPTH // 2}", DocumentSource.NOTION
    )
    tail = get_hierarchy_node_by_raw_id(
        db_session, f"deep_{tag}_{DEEP_CHAIN_DEPTH - 1}", DocumentSource.NOTION
    )
    assert head is not None
    assert middle is not None
    assert tail is not None
    # Tail's parent should be the second-to-last node.
    parent_of_tail = get_hierarchy_node_by_raw_id(
        db_session, f"deep_{tag}_{DEEP_CHAIN_DEPTH - 2}", DocumentSource.NOTION
    )
    assert parent_of_tail is not None
    assert tail.parent_id == parent_of_tail.id

    db_session.rollback()


@pytest.mark.usefixtures("notion_source_node")
def test_upsert_parents_handles_parent_cycle(
    db_session: Session,
) -> None:
    """A two-node parent cycle must not raise or loop forever."""
    tag = uuid4().hex[:8]
    a_id = f"cycle_a_{tag}"
    b_id = f"cycle_b_{tag}"
    nodes = [
        PydanticHierarchyNode(
            raw_node_id=a_id,
            raw_parent_id=b_id,
            display_name=f"Cycle A {tag}",
            node_type=HierarchyNodeType.PAGE,
        ),
        PydanticHierarchyNode(
            raw_node_id=b_id,
            raw_parent_id=a_id,
            display_name=f"Cycle B {tag}",
            node_type=HierarchyNodeType.PAGE,
        ),
    ]

    # Must complete without RecursionError. The cycle is broken at one of the
    # two nodes — the broken edge resolves to the SOURCE node — but both nodes
    # should still be persisted.
    upsert_hierarchy_nodes_batch(db_session, nodes, DocumentSource.NOTION, commit=False)

    a_row = get_hierarchy_node_by_raw_id(db_session, a_id, DocumentSource.NOTION)
    b_row = get_hierarchy_node_by_raw_id(db_session, b_id, DocumentSource.NOTION)
    assert a_row is not None
    assert b_row is not None

    db_session.rollback()


@pytest.mark.usefixtures("notion_source_node")
def test_upsert_parents_handles_self_parent(
    db_session: Session,
) -> None:
    """A node whose raw_parent_id equals its own raw_node_id must not loop."""
    tag = uuid4().hex[:8]
    self_id = f"self_{tag}"
    nodes = [
        PydanticHierarchyNode(
            raw_node_id=self_id,
            raw_parent_id=self_id,
            display_name=f"Self {tag}",
            node_type=HierarchyNodeType.PAGE,
        ),
    ]

    upsert_hierarchy_nodes_batch(db_session, nodes, DocumentSource.NOTION, commit=False)

    row = get_hierarchy_node_by_raw_id(db_session, self_id, DocumentSource.NOTION)
    assert row is not None

    db_session.rollback()
