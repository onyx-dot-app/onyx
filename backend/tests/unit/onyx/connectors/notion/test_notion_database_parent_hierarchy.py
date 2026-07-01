"""Tests for standalone-database parent page hierarchy node emission.

When _yield_database_hierarchy_nodes discovers that a database's parent is a
page, it records that page ID in _database_parent_page_ids.  _read_pages then
emits a hierarchy node for that page even if its BlockReadOutput is empty
(no child pages, no inline databases), so the STUB created during database
upsert can be promoted.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.models import HierarchyNode
from onyx.connectors.notion.connector import BlockReadOutput
from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.connector import NotionPage
from onyx.db.enums import HierarchyNodeType


def _make_connector() -> NotionConnector:
    connector = NotionConnector()
    connector.load_credentials({"notion_integration_token": "fake-token"})
    connector.workspace_id = "ws-1"
    return connector


def _make_page(
    page_id: str,
    parent: dict,
    url: str | None = None,
) -> NotionPage:
    return NotionPage(
        id=page_id,
        created_time="2026-01-01T00:00:00.000Z",
        last_edited_time="2026-01-01T00:00:00.000Z",
        in_trash=False,
        properties={"Name": {"type": "title", "title": [{"plain_text": page_id}]}},
        url=url or f"https://notion.so/{page_id}",
        parent=parent,
    )


def _make_db_page(
    db_id: str,
    parent: dict,
    name: str = "Test DB",
) -> NotionPage:
    return NotionPage(
        id=db_id,
        created_time="2026-01-01T00:00:00.000Z",
        last_edited_time="2026-01-01T00:00:00.000Z",
        in_trash=False,
        properties={},
        url=f"https://notion.so/{db_id}",
        parent=parent,
        database_name=name,
    )


class TestDatabaseParentPageTracking:
    def test_page_id_parent_is_recorded(self) -> None:
        """A database whose parent type is page_id is added to _database_parent_page_ids."""
        connector = _make_connector()

        search_response = MagicMock()
        search_response.results = [
            {"id": "ds-1", "parent": {"database_id": "db-1"}},
        ]
        search_response.has_more = False

        db_page = _make_db_page("db-1", parent={"type": "page_id", "page_id": "page-P"})

        with (
            patch.object(connector, "_search_notion", return_value=search_response),
            patch.object(connector, "_fetch_database_as_page", return_value=db_page),
        ):
            list(connector._yield_database_hierarchy_nodes())

        assert "page-P" in connector._database_parent_page_ids

    def test_workspace_parent_not_recorded(self) -> None:
        """A database whose parent is the workspace root is not tracked."""
        connector = _make_connector()

        search_response = MagicMock()
        search_response.results = [
            {"id": "ds-1", "parent": {"database_id": "db-1"}},
        ]
        search_response.has_more = False

        db_page = _make_db_page("db-1", parent={"type": "workspace", "workspace": True})

        with (
            patch.object(connector, "_search_notion", return_value=search_response),
            patch.object(connector, "_fetch_database_as_page", return_value=db_page),
        ):
            list(connector._yield_database_hierarchy_nodes())

        assert not connector._database_parent_page_ids

    def test_failed_fetch_does_not_record(self) -> None:
        """A database whose fetch fails (exception path) is not recorded."""
        import requests

        connector = _make_connector()

        search_response = MagicMock()
        search_response.results = [
            {"id": "ds-1", "parent": {"database_id": "db-1"}},
        ]
        search_response.has_more = False

        with (
            patch.object(connector, "_search_notion", return_value=search_response),
            patch.object(
                connector,
                "_fetch_database_as_page",
                side_effect=requests.exceptions.HTTPError("404"),
            ),
        ):
            list(connector._yield_database_hierarchy_nodes())

        assert not connector._database_parent_page_ids


class TestReadPagesEmitsHierarchyNodeForDatabaseParent:
    def test_database_parent_page_emits_hierarchy_node_without_children(self) -> None:
        """A page in _database_parent_page_ids emits a hierarchy node from _read_pages
        even when _read_blocks returns an empty BlockReadOutput."""
        connector = _make_connector()
        connector._database_parent_page_ids = {"page-P"}

        page = _make_page("page-P", parent={"type": "workspace", "workspace": True})
        empty_block_output = BlockReadOutput(
            blocks=[], child_page_ids=[], hierarchy_nodes=[]
        )

        with patch.object(connector, "_read_blocks", return_value=empty_block_output):
            yielded = list(connector._read_pages([page]))

        hierarchy_nodes = [item for item in yielded if isinstance(item, HierarchyNode)]
        assert any(n.raw_node_id == "page-P" for n in hierarchy_nodes), (
            "Expected a hierarchy node for the database-parent page, got none. "
            f"Yielded: {yielded}"
        )
        node = next(n for n in hierarchy_nodes if n.raw_node_id == "page-P")
        assert node.node_type == HierarchyNodeType.PAGE

    def test_non_database_parent_page_does_not_emit_hierarchy_node(self) -> None:
        """A page NOT in _database_parent_page_ids with no block children emits no
        hierarchy node (existing behavior preserved)."""
        connector = _make_connector()
        # _database_parent_page_ids is empty

        page = _make_page("page-Q", parent={"type": "workspace", "workspace": True})
        empty_block_output = BlockReadOutput(
            blocks=[], child_page_ids=[], hierarchy_nodes=[]
        )

        with patch.object(connector, "_read_blocks", return_value=empty_block_output):
            yielded = list(connector._read_pages([page]))

        hierarchy_nodes = [item for item in yielded if isinstance(item, HierarchyNode)]
        assert not any(n.raw_node_id == "page-Q" for n in hierarchy_nodes), (
            "Expected no hierarchy node for a leaf page, but one was emitted."
        )
