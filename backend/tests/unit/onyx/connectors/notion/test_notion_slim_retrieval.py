"""Tests for the Notion slim (pruning) enumeration.

Pruning deletes any indexed doc the enumeration does not return, so the core
guarantee is coverage: `retrieve_all_slim_docs` must return every ID the full
load path indexes — including pages the search API misses (child pages and
database rows found only by block traversal).
"""

from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any, Iterator
from unittest.mock import patch

from onyx.connectors.models import Document, HierarchyNode, SlimDocument
from onyx.connectors.notion.connector import (
    NotionConnector,
    NotionDataSource,
    NotionPage,
    NotionSearchResponse,
)

_CREATED = "2026-01-01T00:00:00.000Z"


def _raw_page(
    page_id: str, parent: dict[str, Any], title: str | None = None
) -> dict[str, Any]:
    return {
        "id": page_id,
        "created_time": _CREATED,
        "last_edited_time": _CREATED,
        "in_trash": False,
        "properties": (
            {"Name": {"type": "title", "title": [{"plain_text": title}]}}
            if title
            else {}
        ),
        "url": f"https://notion.so/{page_id}",
        "parent": parent,
    }


# Workspace layout:
#   page-a (workspace root): paragraph, child_page page-c, child_database db-1
#   page-b: row of db-1 (returned by search)
#   page-c: child page of page-a (NOT returned by search)
#   page-e: row of db-1 (NOT returned by search)
#   page-f: blank + untitled (returned by search; indexing skips it, slim must too)
_RAW_PAGES: dict[str, dict[str, Any]] = {
    "page-a": _raw_page("page-a", {"type": "workspace", "workspace": True}, "A"),
    "page-b": _raw_page(
        "page-b", {"type": "data_source_id", "data_source_id": "ds-1"}, "B"
    ),
    "page-c": _raw_page("page-c", {"type": "block_id", "block_id": "blk-x"}, "C"),
    "page-e": _raw_page(
        "page-e", {"type": "data_source_id", "data_source_id": "ds-1"}, "E"
    ),
    "page-f": _raw_page("page-f", {"type": "workspace", "workspace": True}),
}

_BLOCKS: dict[str, list[dict[str, Any]]] = {
    "page-a": [
        {
            "id": "para-1",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": "Hello"}}]},
            "has_children": False,
        },
        {
            "id": "page-c",
            "type": "child_page",
            "child_page": {"title": "C"},
            "has_children": True,
        },
        {
            "id": "db-1",
            "type": "child_database",
            "child_database": {"title": "DB One"},
            "has_children": False,
        },
    ],
    "page-c": [
        {
            "id": "para-2",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": "C text"}}]},
            "has_children": False,
        },
    ],
}


def _search(query_dict: dict[str, Any]) -> NotionSearchResponse:
    if query_dict["filter"]["value"] == "data_source":
        return NotionSearchResponse(
            results=[{"id": "ds-1", "parent": {"database_id": "db-1"}}],
            next_cursor=None,
            has_more=False,
        )
    return NotionSearchResponse(
        results=[_RAW_PAGES["page-a"], _RAW_PAGES["page-b"], _RAW_PAGES["page-f"]],
        next_cursor=None,
        has_more=False,
    )


def _fetch_child_blocks(block_id: str, _cursor: str | None = None) -> dict[str, Any]:
    return {"results": _BLOCKS.get(block_id, []), "next_cursor": None}


def _fetch_data_source(
    _data_source_id: str, _cursor: str | None = None
) -> dict[str, Any]:
    return {
        "results": [
            {"id": "page-e", "object": "page", "properties": {}},
            {"id": "page-b", "object": "page", "properties": {}},
        ],
        "next_cursor": None,
    }


def _mock_workspace(connector: NotionConnector, stack: ExitStack) -> dict[str, Any]:
    """Patch all Notion API helpers; returns the mocks for call assertions."""
    mocks = {
        "_search_notion": stack.enter_context(
            patch.object(connector, "_search_notion", side_effect=_search)
        ),
        "_fetch_child_blocks": stack.enter_context(
            patch.object(
                connector, "_fetch_child_blocks", side_effect=_fetch_child_blocks
            )
        ),
        "_fetch_page": stack.enter_context(
            patch.object(
                connector,
                "_fetch_page",
                side_effect=lambda page_id: NotionPage(**_RAW_PAGES[page_id]),
            )
        ),
        "_fetch_workspace_info": stack.enter_context(
            patch.object(
                connector,
                "_fetch_workspace_info",
                return_value=("ws-1", "Test WS"),
            )
        ),
        "_fetch_database_as_page": stack.enter_context(
            patch.object(
                connector,
                "_fetch_database_as_page",
                side_effect=lambda db_id: NotionPage(
                    id=db_id,
                    created_time=_CREATED,
                    last_edited_time=_CREATED,
                    in_trash=False,
                    properties={},
                    url=f"https://notion.so/{db_id}",
                    database_name="DB One",
                    parent={"type": "page_id", "page_id": "page-a"},
                ),
            )
        ),
        "_fetch_data_sources_for_database": stack.enter_context(
            patch.object(
                connector,
                "_fetch_data_sources_for_database",
                return_value=[NotionDataSource(id="ds-1", name="DS One")],
            )
        ),
        "_fetch_data_source": stack.enter_context(
            patch.object(
                connector, "_fetch_data_source", side_effect=_fetch_data_source
            )
        ),
    }
    return mocks


def _flatten(batches: Iterator[list[Any]]) -> list[Any]:
    return [item for batch in batches for item in batch]


class TestSlimCoverage:
    def test_slim_ids_match_full_load_ids(self) -> None:
        """The core pruning-safety guarantee, checked against the same
        mocked workspace: slim ids == full-load ids, slim hierarchy
        nodes ⊇ full-load hierarchy nodes."""
        full_connector = NotionConnector()
        with ExitStack() as stack:
            _mock_workspace(full_connector, stack)
            full_items = _flatten(full_connector.load_from_state())

        slim_connector = NotionConnector()
        with ExitStack() as stack:
            _mock_workspace(slim_connector, stack)
            slim_items = _flatten(slim_connector.retrieve_all_slim_docs())

        full_doc_ids = {i.id for i in full_items if isinstance(i, Document)}
        slim_doc_ids = {i.id for i in slim_items if isinstance(i, SlimDocument)}
        assert full_doc_ids == {"page-a", "page-b", "page-c", "page-e"}
        # Equality both ways: page-f (blank + untitled) is skipped by indexing,
        # so slim must not emit it either — else its stale doc would never prune
        assert slim_doc_ids == full_doc_ids

        full_nodes = {i.raw_node_id for i in full_items if isinstance(i, HierarchyNode)}
        slim_nodes = {i.raw_node_id for i in slim_items if isinstance(i, HierarchyNode)}
        assert full_nodes == {"ws-1", "db-1", "page-a"}
        assert slim_nodes >= full_nodes

    def test_slim_docs_carry_parents_and_created_at(self) -> None:
        connector = NotionConnector()
        with ExitStack() as stack:
            mocks = _mock_workspace(connector, stack)
            items = _flatten(connector.retrieve_all_slim_docs())

        slim_by_id = {i.id: i for i in items if isinstance(i, SlimDocument)}
        assert slim_by_id["page-a"].parent_hierarchy_raw_node_id == "ws-1"
        assert slim_by_id["page-b"].parent_hierarchy_raw_node_id == "db-1"
        assert slim_by_id["page-c"].parent_hierarchy_raw_node_id == "page-a"
        assert slim_by_id["page-e"].parent_hierarchy_raw_node_id == "db-1"
        assert slim_by_id["page-a"].doc_created_at == datetime(
            2026, 1, 1, tzinfo=timezone.utc
        )

        # Only non-search pages are fetched individually (lazily, when popped)
        fetched = {call.args[0] for call in mocks["_fetch_page"].call_args_list}
        assert fetched == {"page-c", "page-e"}

    def test_root_page_mode_skips_search(self) -> None:
        connector = NotionConnector(root_page_id="page-a")
        with ExitStack() as stack:
            mocks = _mock_workspace(connector, stack)
            items = _flatten(connector.retrieve_all_slim_docs())

        slim_doc_ids = {i.id for i in items if isinstance(i, SlimDocument)}
        assert slim_doc_ids == {"page-a", "page-b", "page-c", "page-e"}
        mocks["_search_notion"].assert_not_called()

    def test_non_recursive_mode_does_not_follow_children(self) -> None:
        connector = NotionConnector(recursive_index_enabled=False)
        with ExitStack() as stack:
            mocks = _mock_workspace(connector, stack)
            items = _flatten(connector.retrieve_all_slim_docs())

        slim_doc_ids = {i.id for i in items if isinstance(i, SlimDocument)}
        assert slim_doc_ids == {"page-a", "page-b"}
        node_ids = {i.raw_node_id for i in items if isinstance(i, HierarchyNode)}
        assert node_ids == {"ws-1", "db-1", "page-a"}
        mocks["_fetch_page"].assert_not_called()


class TestSlimBlockWalk:
    def test_cyclic_block_references_terminate(self) -> None:
        connector = NotionConnector()

        cycle: dict[str, dict[str, Any]] = {
            "page-1": {
                "results": [
                    {
                        "id": "block-1",
                        "type": "synced_block",
                        "synced_block": {},
                        "has_children": True,
                    }
                ],
                "next_cursor": None,
            },
            "block-1": {
                "results": [
                    {
                        "id": "page-1",
                        "type": "synced_block",
                        "synced_block": {},
                        "has_children": True,
                    }
                ],
                "next_cursor": None,
            },
        }

        with patch.object(
            connector,
            "_fetch_child_blocks",
            side_effect=lambda block_id, _cursor=None: cycle[block_id],
        ):
            output = connector._read_blocks("page-1", is_slim=True)

        assert output.child_page_ids == []
        assert output.blocks == []
