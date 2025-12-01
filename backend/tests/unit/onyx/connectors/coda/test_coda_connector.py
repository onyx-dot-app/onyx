import sys
from unittest.mock import MagicMock

import pytest

from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.coda.connector import CodaPage

# Mock dependencies to avoid installing everything
sys.modules["fastapi_users"] = MagicMock()
sys.modules["fastapi_users.schemas"] = MagicMock()
sys.modules["onyx.auth"] = MagicMock()
sys.modules["onyx.auth.schemas"] = MagicMock()

# Mock app_configs
app_configs = MagicMock()
app_configs.INDEX_BATCH_SIZE = 10
sys.modules["onyx.configs.app_configs"] = app_configs


@pytest.fixture
def mock_connector():
    connector = CodaConnector()
    connector.doc_ids = None
    return connector


def test_get_page_path(mock_connector):
    # Setup pages
    page1 = CodaPage(
        id="p1",
        type="page",
        href="href1",
        browserLink="link1",
        name="Root Page",
        contentType="canvas",
        isHidden=False,
        createdAt="2023-01-01T00:00:00Z",
        updatedAt="2023-01-01T00:00:00Z",
        children=[],
    )
    page2 = CodaPage(
        id="p2",
        type="page",
        href="href2",
        browserLink="link2",
        name="Child Page",
        contentType="canvas",
        isHidden=False,
        createdAt="2023-01-01T00:00:00Z",
        updatedAt="2023-01-01T00:00:00Z",
        children=[],
        parent={"id": "p1"},
    )
    page3 = CodaPage(
        id="p3",
        type="page",
        href="href3",
        browserLink="link3",
        name="Grandchild Page",
        contentType="canvas",
        isHidden=False,
        createdAt="2023-01-01T00:00:00Z",
        updatedAt="2023-01-01T00:00:00Z",
        children=[],
        parent={"id": "p2"},
    )

    page_map = {"p1": page1, "p2": page2, "p3": page3}

    # Test paths
    assert mock_connector._get_page_path(page1, page_map) == "Root Page"
    assert mock_connector._get_page_path(page2, page_map) == "Root Page / Child Page"
    assert (
        mock_connector._get_page_path(page3, page_map)
        == "Root Page / Child Page / Grandchild Page"
    )


def test_load_from_state_hierarchy(mock_connector):
    # Mock API responses
    mock_connector._fetch_docs = MagicMock(
        return_value={
            "items": [
                {
                    "id": "d1",
                    "type": "doc",
                    "href": "dhref",
                    "browserLink": "dlink",
                    "name": "Test Doc",
                    "owner": "me",
                    "ownerName": "Me",
                    "createdAt": "2023-01-01T00:00:00Z",
                    "updatedAt": "2023-01-01T00:00:00Z",
                    "workspace": {},
                    "folder": {},
                }
            ]
        }
    )

    # Page 1: Root
    # Page 2: Child of Page 1
    mock_connector._fetch_pages = MagicMock(
        return_value={
            "items": [
                {
                    "id": "p1",
                    "type": "page",
                    "href": "href1",
                    "browserLink": "link1",
                    "name": "Root",
                    "contentType": "canvas",
                    "isHidden": False,
                    "createdAt": "2023-01-01T00:00:00Z",
                    "updatedAt": "2023-01-01T00:00:00Z",
                    "icon": {"name": "emoji", "value": "📄"},
                },
                {
                    "id": "p2",
                    "type": "page",
                    "href": "href2",
                    "browserLink": "link2",
                    "name": "Child",
                    "contentType": "canvas",
                    "isHidden": False,
                    "createdAt": "2023-01-01T00:00:00Z",
                    "updatedAt": "2023-01-01T00:00:00Z",
                    "parent": {"id": "p1"},
                },
            ]
        }
    )

    mock_connector._export_page_content = MagicMock(return_value="Content")

    # Run load_from_state
    docs = list(mock_connector.load_from_state())

    # Verify documents
    assert len(docs) == 2

    # Sort by page_id to ensure order
    docs.sort(key=lambda d: d.metadata["page_id"])

    doc1 = docs[0]  # p1
    assert doc1.metadata["page_id"] == "p1"
    assert doc1.metadata["path"] == "Root"
    assert doc1.metadata["icon"] == "{'name': 'emoji', 'value': '📄'}"
    assert "parent_page_id" not in doc1.metadata

    doc2 = docs[1]  # p2
    assert doc2.metadata["page_id"] == "p2"
    assert doc2.metadata["path"] == "Root / Child"
    assert doc2.metadata["parent_page_id"] == "p1"
