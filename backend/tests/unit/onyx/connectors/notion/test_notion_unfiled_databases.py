"""Unit tests for the Notion connector's end-of-run database reconciliation.

Covers re-emitting database hierarchy nodes with their final parent:
- databases whose parent page became a node nest under that page (ordering fix)
- databases whose parent never materialized are collected under a synthetic
  per-workspace "Unfiled" node instead of scattering under SOURCE.
"""

from unittest.mock import patch

from onyx.connectors.models import HierarchyNode
from onyx.connectors.notion.connector import _TrackedDatabase
from onyx.connectors.notion.connector import _UNFILED_DATABASES_DISPLAY_NAME
from onyx.connectors.notion.connector import _unfiled_node_raw_id
from onyx.connectors.notion.connector import _UNFILED_NODE_SUFFIX
from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.connector import NotionPage
from onyx.connectors.notion.connector import NotionSearchResponse
from onyx.db.enums import HierarchyNodeType


def _make_connector() -> NotionConnector:
    connector = NotionConnector()
    connector.load_credentials({"notion_integration_token": "fake-token"})
    return connector


def _make_db_page(
    db_id: str, parent: dict, name: str = "My DB", url: str = "https://notion.so/db"
) -> NotionPage:
    return NotionPage(
        id=db_id,
        created_time="2024-01-01T00:00:00.000Z",
        last_edited_time="2024-01-01T00:00:00.000Z",
        in_trash=False,
        properties={},
        url=url,
        database_name=name,
        parent=parent,
    )


class TestReconcileDatabaseParents:
    def test_orphan_routed_to_unfiled(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        connector.seen_hierarchy_node_raw_ids = {"ws-1", "db-1"}
        connector._tracked_databases = [
            _TrackedDatabase(
                raw_node_id="db-1",
                parent_raw_id="page-x",  # never became a node
                display_name="My DB",
                link="https://notion.so/db1",
            )
        ]

        nodes = list(connector._reconcile_database_parents())

        unfiled_id = _unfiled_node_raw_id("ws-1")
        unfiled = [n for n in nodes if n.raw_node_id == unfiled_id]
        assert len(unfiled) == 1
        assert unfiled[0].raw_parent_id == "ws-1"
        assert unfiled[0].node_type == HierarchyNodeType.PAGE
        assert unfiled[0].display_name == _UNFILED_DATABASES_DISPLAY_NAME

        db_node = [n for n in nodes if n.raw_node_id == "db-1"]
        assert len(db_node) == 1
        assert db_node[0].raw_parent_id == unfiled_id
        assert db_node[0].node_type == HierarchyNodeType.DATABASE

        # Unfiled node must be emitted before the database that references it.
        assert nodes[0].raw_node_id == unfiled_id

    def test_resolved_parent_kept_no_unfiled(self) -> None:
        """Ordering fix: a database whose parent page DID become a node this run
        nests under that page, and no Unfiled node is created."""
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        connector.seen_hierarchy_node_raw_ids = {"ws-1", "db-1", "page-x"}
        connector._tracked_databases = [
            _TrackedDatabase(
                raw_node_id="db-1",
                parent_raw_id="page-x",  # became a node this run
                display_name="My DB",
                link="https://notion.so/db1",
            )
        ]

        nodes = list(connector._reconcile_database_parents())

        assert all(not n.raw_node_id.endswith(_UNFILED_NODE_SUFFIX) for n in nodes)
        db_node = [n for n in nodes if n.raw_node_id == "db-1"]
        assert len(db_node) == 1
        assert db_node[0].raw_parent_id == "page-x"

    def test_mixed_resolved_and_orphan(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        connector.seen_hierarchy_node_raw_ids = {"ws-1", "db-1", "db-2", "page-x"}
        connector._tracked_databases = [
            _TrackedDatabase(
                raw_node_id="db-1",
                parent_raw_id="page-x",
                display_name="Resolved DB",
                link=None,
            ),
            _TrackedDatabase(
                raw_node_id="db-2",
                parent_raw_id="page-missing",
                display_name="Orphan DB",
                link=None,
            ),
        ]

        nodes = list(connector._reconcile_database_parents())
        by_id = {n.raw_node_id: n for n in nodes}
        unfiled_id = _unfiled_node_raw_id("ws-1")

        assert unfiled_id in by_id
        assert by_id["db-1"].raw_parent_id == "page-x"
        assert by_id["db-2"].raw_parent_id == unfiled_id

    def test_no_tracked_databases_is_noop(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"
        assert list(connector._reconcile_database_parents()) == []

    def test_unfiled_id_is_workspace_scoped(self) -> None:
        connector_a = _make_connector()
        connector_a.workspace_id = "ws-a"
        connector_a.seen_hierarchy_node_raw_ids = {"ws-a", "db-1"}
        connector_a._tracked_databases = [
            _TrackedDatabase(
                raw_node_id="db-1", parent_raw_id="page-x", display_name="A", link=None
            )
        ]
        connector_b = _make_connector()
        connector_b.workspace_id = "ws-b"
        connector_b.seen_hierarchy_node_raw_ids = {"ws-b", "db-1"}
        connector_b._tracked_databases = [
            _TrackedDatabase(
                raw_node_id="db-1", parent_raw_id="page-x", display_name="B", link=None
            )
        ]

        nodes_a = list(connector_a._reconcile_database_parents())
        nodes_b = list(connector_b._reconcile_database_parents())

        unfiled_a = next(
            n for n in nodes_a if n.raw_node_id.endswith(_UNFILED_NODE_SUFFIX)
        )
        unfiled_b = next(
            n for n in nodes_b if n.raw_node_id.endswith(_UNFILED_NODE_SUFFIX)
        )
        assert unfiled_a.raw_node_id == _unfiled_node_raw_id("ws-a")
        assert unfiled_b.raw_node_id == _unfiled_node_raw_id("ws-b")
        assert unfiled_a.raw_node_id != unfiled_b.raw_node_id


class TestYieldDatabaseHierarchyNodesTracking:
    def test_tracks_non_workspace_parent_skips_workspace_parent(self) -> None:
        connector = _make_connector()
        connector.workspace_id = "ws-1"

        search_resp = NotionSearchResponse(
            results=[
                {"id": "ds-1", "parent": {"database_id": "db-page"}},
                {"id": "ds-2", "parent": {"database_id": "db-top"}},
            ],
            next_cursor=None,
            has_more=False,
        )

        def fake_fetch_db_as_page(db_id: str) -> NotionPage:
            if db_id == "db-page":
                return _make_db_page(db_id, {"type": "page_id", "page_id": "page-x"})
            return _make_db_page(db_id, {"type": "workspace"})

        with (
            patch.object(connector, "_search_notion", return_value=search_resp),
            patch.object(
                connector, "_fetch_database_as_page", side_effect=fake_fetch_db_as_page
            ),
        ):
            nodes = [
                n
                for n in connector._yield_database_hierarchy_nodes()
                if isinstance(n, HierarchyNode)
            ]

        # Both databases are yielded in the prepass.
        assert {n.raw_node_id for n in nodes} == {"db-page", "db-top"}
        # Only the page-parented database is tracked for reconciliation.
        tracked_ids = {td.raw_node_id for td in connector._tracked_databases}
        assert tracked_ids == {"db-page"}
        tracked = connector._tracked_databases[0]
        assert tracked.parent_raw_id == "page-x"


class TestLoadFromStateReconciliation:
    def test_orphan_database_reemitted_under_unfiled(self) -> None:
        connector = _make_connector()

        def fake_search(query_dict: dict) -> NotionSearchResponse:
            value = query_dict["filter"]["value"]
            if value == "data_source":
                return NotionSearchResponse(
                    results=[{"id": "ds-1", "parent": {"database_id": "db-1"}}],
                    next_cursor=None,
                    has_more=False,
                )
            # No pages returned -> parent page never becomes a node.
            return NotionSearchResponse(results=[], next_cursor=None, has_more=False)

        def fake_fetch_db_as_page(db_id: str) -> NotionPage:
            return _make_db_page(db_id, {"type": "page_id", "page_id": "page-x"})

        with (
            patch.object(
                connector,
                "_fetch_workspace_info",
                return_value=("ws-1", "My Workspace"),
            ),
            patch.object(connector, "_search_notion", side_effect=fake_search),
            patch.object(
                connector, "_fetch_database_as_page", side_effect=fake_fetch_db_as_page
            ),
        ):
            nodes: list[HierarchyNode] = [
                item
                for batch in connector.load_from_state()
                for item in batch
                if isinstance(item, HierarchyNode)
            ]

        # Workspace node is emitted first.
        assert nodes[0].raw_node_id == "ws-1"
        assert nodes[0].node_type == HierarchyNodeType.WORKSPACE

        unfiled_id = _unfiled_node_raw_id("ws-1")
        assert any(n.raw_node_id == unfiled_id for n in nodes)

        # db-1 is yielded twice: once in the prepass (parent page-x) and once
        # re-emitted at the end under the Unfiled node.
        db_nodes = [n for n in nodes if n.raw_node_id == "db-1"]
        assert len(db_nodes) == 2
        assert db_nodes[0].raw_parent_id == "page-x"
        assert db_nodes[-1].raw_parent_id == unfiled_id
