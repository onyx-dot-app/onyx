import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.notion.connector import NotionConnector


def compare_hierarchy_nodes(
    yielded_nodes: list[HierarchyNode],
    expected_nodes: list[HierarchyNode],
) -> None:
    """Compare yielded HierarchyNodes against expected ground truth.

    Compares nodes by their essential fields (raw_node_id, raw_parent_id, display_name, link).
    Order does not matter.
    """
    if not expected_nodes:
        # Empty ground truth - skip comparison for now
        return

    yielded_set = {
        (n.raw_node_id, n.raw_parent_id, n.display_name, n.link) for n in yielded_nodes
    }
    expected_set = {
        (n.raw_node_id, n.raw_parent_id, n.display_name, n.link) for n in expected_nodes
    }

    missing = expected_set - yielded_set
    extra = yielded_set - expected_set

    assert not missing, f"Missing expected HierarchyNodes: {missing}"
    assert not extra, f"Unexpected HierarchyNodes: {extra}"


@pytest.fixture
def notion_connector() -> NotionConnector:
    """Create a NotionConnector with credentials from environment variables"""
    connector = NotionConnector()
    connector.load_credentials(
        {
            "notion_integration_token": os.environ["NOTION_INTEGRATION_TOKEN"],
        }
    )
    return connector


def test_notion_connector_basic(notion_connector: NotionConnector) -> None:
    """Test the NotionConnector with a real Notion page.

    Uses a Notion workspace under the onyx-test.com domain.
    """
    doc_batch_generator = notion_connector.poll_source(0, time.time())

    # Collect all documents and hierarchy nodes from all batches
    documents: list[Document] = []
    hierarchy_nodes: list[HierarchyNode] = []
    for doc_batch in doc_batch_generator:
        for item in doc_batch:
            if isinstance(item, HierarchyNode):
                hierarchy_nodes.append(item)
            else:
                documents.append(item)

    # Verify document count
    assert (
        len(documents) == 5
    ), "Expected exactly 5 documents (root, two children, table entry, and table entry child)"

    # Verify HierarchyNodes against ground truth (empty for now)
    expected_hierarchy_nodes: list[HierarchyNode] = []
    compare_hierarchy_nodes(hierarchy_nodes, expected_hierarchy_nodes)

    # Find root and child documents by semantic identifier
    root_doc = None
    child1_doc = None
    child2_doc = None
    table_entry_doc = None
    table_entry_child_doc = None
    for doc in documents:
        if doc.semantic_identifier == "Root":
            root_doc = doc
        elif doc.semantic_identifier == "Child1":
            child1_doc = doc
        elif doc.semantic_identifier == "Child2":
            child2_doc = doc
        elif doc.semantic_identifier == "table-entry01":
            table_entry_doc = doc
        elif doc.semantic_identifier == "Child-table-entry01":
            table_entry_child_doc = doc

    assert root_doc is not None, "Root document not found"
    assert child1_doc is not None, "Child1 document not found"
    assert child2_doc is not None, "Child2 document not found"
    assert table_entry_doc is not None, "Table entry document not found"
    assert table_entry_child_doc is not None, "Table entry child document not found"

    # Verify root document structure
    assert root_doc.id is not None
    assert root_doc.source == DocumentSource.NOTION

    # Section checks for root
    assert len(root_doc.sections) == 1
    root_section = root_doc.sections[0]

    # Content specific checks for root
    assert root_section.text == "\nroot"
    assert root_section.link is not None
    assert root_section.link.startswith("https://www.notion.so/")

    # Verify child1 document structure
    assert child1_doc.id is not None
    assert child1_doc.source == DocumentSource.NOTION

    # Section checks for child1
    assert len(child1_doc.sections) == 1
    child1_section = child1_doc.sections[0]

    # Content specific checks for child1
    assert child1_section.text == "\nchild1"
    assert child1_section.link is not None
    assert child1_section.link.startswith("https://www.notion.so/")

    # Verify child2 document structure (includes database)
    assert child2_doc.id is not None
    assert child2_doc.source == DocumentSource.NOTION

    # Section checks for child2
    assert len(child2_doc.sections) == 2  # One for content, one for database
    child2_section = child2_doc.sections[0]
    child2_db_section = child2_doc.sections[1]

    # Content specific checks for child2
    assert child2_section.text == "\nchild2"
    assert child2_section.link is not None
    assert child2_section.link.startswith("https://www.notion.so/")

    # Database section checks for child2
    assert child2_db_section.text is not None
    assert child2_db_section.text.strip() != ""  # Should contain some database content
    assert child2_db_section.link is not None
    assert child2_db_section.link.startswith("https://www.notion.so/")

    # Verify table entry document structure
    assert table_entry_doc.id is not None
    assert table_entry_doc.source == DocumentSource.NOTION

    # Section checks for table entry
    assert len(table_entry_doc.sections) == 1
    table_entry_section = table_entry_doc.sections[0]

    # Content specific checks for table entry
    assert table_entry_section.text == "\ntable-entry01"
    assert table_entry_section.link is not None
    assert table_entry_section.link.startswith("https://www.notion.so/")

    # Verify table entry child document structure
    assert table_entry_child_doc.id is not None
    assert table_entry_child_doc.source == DocumentSource.NOTION

    # Section checks for table entry child
    assert len(table_entry_child_doc.sections) == 1
    table_entry_child_section = table_entry_child_doc.sections[0]

    # Content specific checks for table entry child
    assert table_entry_child_section.text == "\nchild-table-entry01"
    assert table_entry_child_section.link is not None
    assert table_entry_child_section.link.startswith("https://www.notion.so/")
