"""Tests for looking up one hierarchy node by id with the user's access."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import get_accessible_hierarchy_node
from onyx.db.models import HierarchyNode
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EMAIL = "alice@example.com"


def _set_ee(monkeypatch: pytest.MonkeyPatch, is_ee: bool) -> None:
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: is_ee)


@pytest.fixture()
def nodes(db_session: Session) -> Generator[dict[str, HierarchyNode], None, None]:
    tag = uuid4().hex[:8]
    by_name = {
        "public": HierarchyNode(
            raw_node_id=f"public_{tag}",
            display_name=f"Public {tag}",
            source=DocumentSource.GOOGLE_DRIVE,
            node_type=HierarchyNodeType.FOLDER,
            is_public=True,
        ),
        "shared": HierarchyNode(
            raw_node_id=f"shared_{tag}",
            display_name=f"Shared {tag}",
            source=DocumentSource.GOOGLE_DRIVE,
            node_type=HierarchyNodeType.FOLDER,
            is_public=False,
            external_user_emails=[_EMAIL],
        ),
        "hidden": HierarchyNode(
            raw_node_id=f"hidden_{tag}",
            display_name=f"Hidden {tag}",
            source=DocumentSource.GOOGLE_DRIVE,
            node_type=HierarchyNodeType.FOLDER,
            is_public=False,
        ),
    }
    db_session.add_all(by_name.values())
    db_session.flush()

    yield by_name

    for node in by_name.values():
        db_session.delete(node)
    db_session.commit()
    fetch_versioned_implementation.cache_clear()


def test_ee_returns_only_nodes_the_user_can_access(
    db_session: Session,
    nodes: dict[str, HierarchyNode],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ee(monkeypatch, True)

    def lookup(name: str) -> HierarchyNode | None:
        return get_accessible_hierarchy_node(db_session, nodes[name].id, _EMAIL, [])

    public = lookup("public")
    assert public is not None and public.display_name == nodes["public"].display_name
    assert lookup("shared") is not None
    assert lookup("hidden") is None


def test_mit_returns_any_existing_node(
    db_session: Session,
    nodes: dict[str, HierarchyNode],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ee(monkeypatch, False)

    assert (
        get_accessible_hierarchy_node(db_session, nodes["hidden"].id, _EMAIL, [])
        is not None
    )
    missing_id = max(node.id for node in nodes.values()) + 1_000_000
    assert get_accessible_hierarchy_node(db_session, missing_id, _EMAIL, []) is None
