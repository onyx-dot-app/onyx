"""get_hierarchy_node_ids_with_ancestors walks the stored parent links from
the seed nodes up to the SOURCE root."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db import hierarchy as hierarchy_db
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import (
    ensure_source_node_exists,
    get_hierarchy_node_by_raw_id,
    get_hierarchy_node_ids_with_ancestors,
    source_has_document_hierarchy_nodes,
    upsert_hierarchy_nodes_batch,
)
from onyx.db.models import Document

_SOURCE = DocumentSource.NOTION
_OTHER_SOURCE = DocumentSource.CONFLUENCE


@pytest.fixture()
def tree(db_session: Session) -> Generator[dict[str, int], None, None]:
    """SOURCE -> root -> a -> b -> c, and a -> d. Maps short names to node
    ids. Rolled back at the end."""
    tag = uuid4().hex[:8]
    raw_ids = {name: f"ancestors_{tag}_{name}" for name in ("root", "a", "b", "c", "d")}
    parents = {"root": None, "a": "root", "b": "a", "c": "b", "d": "a"}
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=raw_ids[name],
                raw_parent_id=raw_ids[parent] if parent else None,
                display_name=name,
                node_type=HierarchyNodeType.FOLDER,
            )
            for name, parent in parents.items()
        ],
        _SOURCE,
        commit=False,
    )
    # The same raw id under another source must not resolve.
    upsert_hierarchy_nodes_batch(
        db_session,
        [
            PydanticHierarchyNode(
                raw_node_id=raw_ids["c"],
                raw_parent_id=None,
                display_name="other c",
                node_type=HierarchyNodeType.FOLDER,
            )
        ],
        _OTHER_SOURCE,
        commit=False,
    )
    ids: dict[str, int] = {}
    for name, raw_id in raw_ids.items():
        node = get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE)
        if node is None:
            raise RuntimeError(f"node {name} was not upserted")
        ids[name] = node.id
    ids["source"] = ensure_source_node_exists(db_session, _SOURCE, commit=False).id
    yield ids
    db_session.rollback()


def _raw(db_session: Session, node_id: int) -> str:
    node = hierarchy_db.get_hierarchy_node_by_id(db_session, node_id)
    if node is None:
        raise RuntimeError(f"node {node_id} not found")
    return node.raw_node_id


def test_raw_seed_walks_up_to_the_source_root(
    db_session: Session, tree: dict[str, int]
) -> None:
    result = get_hierarchy_node_ids_with_ancestors(
        db_session,
        _SOURCE,
        raw_node_ids={_raw(db_session, tree["c"]), "ancestors_unknown_raw_id"},
        node_ids=set(),
    )

    # The sibling d and the other source's node are not ancestors.
    assert result == {tree[n] for n in ("source", "root", "a", "b", "c")}


@pytest.mark.parametrize("batch_size", [1, 1000])
def test_raw_and_id_seeds_merge(
    db_session: Session,
    tree: dict[str, int],
    batch_size: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hierarchy_db, "_ANCESTOR_SEED_BATCH_SIZE", batch_size)

    result = get_hierarchy_node_ids_with_ancestors(
        db_session,
        _SOURCE,
        raw_node_ids={_raw(db_session, tree["b"])},
        node_ids={tree["d"], tree["a"]},
    )

    assert result == {tree[n] for n in ("source", "root", "a", "b", "d")}


def test_no_seeds_is_empty(db_session: Session) -> None:
    assert (
        get_hierarchy_node_ids_with_ancestors(
            db_session, _SOURCE, raw_node_ids=set(), node_ids=set()
        )
        == set()
    )


def test_document_seed_selects_the_node_of_that_document(
    db_session: Session, tree: dict[str, int]
) -> None:
    # A node that is also a document (e.g. a Confluence page) is live when its
    # document is kept, even if no listing yielded the node.
    document_id = f"ancestors_doc_{uuid4().hex[:8]}"
    db_session.add(Document(id=document_id, semantic_id="page"))
    db_session.flush()
    assert not source_has_document_hierarchy_nodes(db_session, _SOURCE)
    node = hierarchy_db.get_hierarchy_node_by_id(db_session, tree["c"])
    if node is None:
        raise RuntimeError("node c not found")
    node.document_id = document_id
    db_session.flush()
    assert source_has_document_hierarchy_nodes(db_session, _SOURCE)
    assert not source_has_document_hierarchy_nodes(db_session, _OTHER_SOURCE)

    result = get_hierarchy_node_ids_with_ancestors(
        db_session,
        _SOURCE,
        raw_node_ids=set(),
        node_ids=set(),
        document_ids={document_id, "ancestors_unknown_document"},
    )

    assert result == {tree[n] for n in ("source", "root", "a", "b", "c")}
