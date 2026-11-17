"""The daily connector tests check the final hierarchy tree, not the order in
which a connector yields parents and children."""

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document, HierarchyNode, TextSection
from onyx.db.enums import HierarchyNodeType
from tests.daily.connectors.utils import check_hierarchy_tree


def _node(raw_id: str, parent: str | None) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=raw_id,
        raw_parent_id=parent,
        display_name=raw_id,
        node_type=HierarchyNodeType.FOLDER,
    )


def _doc(doc_id: str, parent: str | None) -> Document:
    return Document(
        id=doc_id,
        sections=[TextSection(text="text", link=None)],
        source=DocumentSource.GOOGLE_DRIVE,
        semantic_identifier=doc_id,
        metadata={},
        parent_hierarchy_raw_node_id=parent,
    )


def test_children_before_their_parents_pass() -> None:
    # The document and the child folder come before the folders they name.
    documents = [_doc("doc", "child")]
    nodes = [_node("child", "root"), _node("root", None)]

    check_hierarchy_tree(documents, nodes)


def test_a_document_whose_parent_never_comes_fails() -> None:
    with pytest.raises(AssertionError, match="document's parent"):
        check_hierarchy_tree([_doc("doc", "missing")], [_node("root", None)])


def test_a_node_whose_parent_never_comes_fails() -> None:
    with pytest.raises(AssertionError, match="hierarchy node's parent"):
        check_hierarchy_tree([], [_node("child", "missing")])
