"""Tests for hierarchy node access filtering.

Validates that the overlap operator on external_user_group_ids works correctly
with PostgreSQL's VARCHAR[] column type. This specifically tests the fix for
the `character varying[] && text[]` type mismatch error.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.hierarchy import _get_accessible_hierarchy_nodes_for_source
from onyx.configs.constants import DocumentSource
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import HierarchyNode


def _make_node(
    raw_node_id: str,
    display_name: str,
    *,
    is_public: bool = False,
    external_user_emails: list[str] | None = None,
    external_user_group_ids: list[str] | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=raw_node_id,
        display_name=display_name,
        source=DocumentSource.GOOGLE_DRIVE,
        node_type=HierarchyNodeType.FOLDER,
        is_public=is_public,
        external_user_emails=external_user_emails,
        external_user_group_ids=external_user_group_ids,
    )


@pytest.fixture()
def seeded_nodes(db_session: Session) -> Generator[list[HierarchyNode], None, None]:
    """Seed hierarchy nodes with various permission configurations."""
    tag = uuid4().hex[:8]
    nodes = [
        _make_node(
            f"public_{tag}",
            f"Public Folder {tag}",
            is_public=True,
        ),
        _make_node(
            f"email_only_{tag}",
            f"Email-Only Folder {tag}",
            external_user_emails=["alice@example.com"],
        ),
        _make_node(
            f"group_only_{tag}",
            f"Group-Only Folder {tag}",
            external_user_group_ids=["group_engineering", "group_design"],
        ),
        _make_node(
            f"private_{tag}",
            f"Private Folder {tag}",
        ),
    ]
    for node in nodes:
        db_session.add(node)
    db_session.flush()

    yield nodes

    # Cleanup
    for node in nodes:
        db_session.delete(node)
    db_session.commit()


def test_group_overlap_filter(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """The overlap (&&) operator must work on the VARCHAR[] column.

    This is the core regression test: before the cast fix, PostgreSQL raised
    `operator does not exist: character varying[] && text[]`.
    """
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=None,
        external_group_ids=["group_engineering"],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, _, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert group_node.raw_node_id in result_ids
    assert private_node.raw_node_id not in result_ids


def test_email_filter(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """User email matching should return the email-permissioned node."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="alice@example.com",
        external_group_ids=[],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id in result_ids
    assert group_node.raw_node_id not in result_ids
    assert private_node.raw_node_id not in result_ids


def test_no_credentials_returns_only_public(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """With no email and no groups, only public nodes should be returned."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=None,
        external_group_ids=[],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id not in result_ids
    assert group_node.raw_node_id not in result_ids
    assert private_node.raw_node_id not in result_ids


def test_combined_email_and_group(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """Both email and group filters should apply together via OR."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="alice@example.com",
        external_group_ids=["group_design"],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id in result_ids
    assert group_node.raw_node_id in result_ids
    assert private_node.raw_node_id not in result_ids
