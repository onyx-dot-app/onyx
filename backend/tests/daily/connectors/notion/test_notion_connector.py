import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.notion.connector import NotionConnector


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

    # Get first batch of documents
    doc_batch = next(doc_batch_generator)
    assert (
        len(doc_batch) == 5
    ), "Expected exactly 5 documents (root, two children, table entry, and table entry child)"

    # Find root and child documents by semantic identifier
    root_doc = None
    child1_doc = None
    child2_doc = None
    table_entry_doc = None
    table_entry_child_doc = None
    for doc in doc_batch:
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
