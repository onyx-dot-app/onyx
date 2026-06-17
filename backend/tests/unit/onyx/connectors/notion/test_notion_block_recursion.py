"""Regression tests for unbounded recursion in the Notion connector.

A prod page with ~919 nested blocks overflowed `_read_blocks` and crashed the
index attempt. Two triggers are covered: deep nesting (blocks and child pages)
and reference cycles (e.g. mutually-nested synced blocks).
"""

import sys
from typing import Any
from unittest.mock import patch

from onyx.connectors.models import Document
from onyx.connectors.notion.connector import BlockReadOutput
from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.connector import NotionPage

# Pinned per test for determinism; _DEEP is well past it to force the overflow.
_PROD_RECURSION_LIMIT = 1000
_DEEP = 2000


def _make_page(page_id: str) -> NotionPage:
    return NotionPage(
        id=page_id,
        created_time="2026-01-01T00:00:00.000Z",
        last_edited_time="2026-01-01T00:00:00.000Z",
        in_trash=False,
        properties={
            "Name": {"type": "title", "title": [{"plain_text": page_id}]},
        },
        url=f"https://notion.so/{page_id}",
    )


class TestDeepNesting:
    """Condition 1: a genuinely deep (finite) nesting chain."""

    def test_deeply_nested_blocks_do_not_overflow_the_stack(self) -> None:
        connector = NotionConnector()

        def fetch(block_id: str, _cursor: str | None = None) -> dict[str, Any]:
            level = int(block_id.rsplit("-", 1)[1])
            next_level = level + 1
            if next_level > _DEEP:
                return {"results": [], "next_cursor": None}
            return {
                "results": [
                    {
                        "id": f"block-{next_level}",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": f"level {next_level}"}}]
                        },
                        "has_children": next_level < _DEEP,
                    }
                ],
                "next_cursor": None,
            }

        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(_PROD_RECURSION_LIMIT)
        try:
            with patch.object(connector, "_fetch_child_blocks", side_effect=fetch):
                output = connector._read_blocks("block-0")
        finally:
            sys.setrecursionlimit(original_limit)

        # Every nested block is collected exactly once, regardless of traversal order.
        texts = {block.text for block in output.blocks}
        assert len(output.blocks) == _DEEP
        assert len(texts) == _DEEP
        assert "level 1" in texts
        assert f"level {_DEEP}" in texts

    def test_deeply_nested_child_pages_do_not_overflow_the_stack(self) -> None:
        connector = NotionConnector()
        connector.recursive_index_enabled = True
        connector.workspace_id = "ws-1"

        def fake_read_blocks(
            base_block_id: str, _containing_page_id: str | None = None
        ) -> BlockReadOutput:
            level = int(base_block_id.rsplit("-", 1)[1])
            next_level = level + 1
            child_ids = [f"page-{next_level}"] if next_level <= _DEEP else []
            return BlockReadOutput(
                blocks=[], child_page_ids=child_ids, hierarchy_nodes=[]
            )

        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(_PROD_RECURSION_LIMIT)
        try:
            with (
                patch.object(connector, "_read_blocks", side_effect=fake_read_blocks),
                patch.object(
                    connector, "_fetch_page", side_effect=lambda pid: _make_page(pid)
                ),
                patch.object(
                    connector, "_maybe_yield_hierarchy_node", return_value=None
                ),
            ):
                docs = list(connector._read_pages([_make_page("page-0")]))
        finally:
            sys.setrecursionlimit(original_limit)

        # One Document per page in the chain (page-0 .. page-{_DEEP}).
        doc_ids = {d.id for d in docs if isinstance(d, Document)}
        assert len(doc_ids) == _DEEP + 1


class TestReferenceCycle:
    """Condition 2: a synced-block cycle that points back at an ancestor."""

    def test_cyclic_block_references_terminate(self) -> None:
        connector = NotionConnector()

        # block-0 and block-1 mutually reference each other (e.g. two synced
        # blocks each nested inside the other) -> an infinite traversal cycle.
        cycle: dict[str, dict[str, Any]] = {
            "block-0": {
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
                        "id": "block-0",
                        "type": "synced_block",
                        "synced_block": {},
                        "has_children": True,
                    }
                ],
                "next_cursor": None,
            },
        }

        def fetch(block_id: str, _cursor: str | None = None) -> dict[str, Any]:
            return cycle[block_id]

        original_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(_PROD_RECURSION_LIMIT)
        try:
            with patch.object(connector, "_fetch_child_blocks", side_effect=fetch):
                output = connector._read_blocks("block-0")
        finally:
            sys.setrecursionlimit(original_limit)

        # The cycle must be detected and broken so traversal terminates.
        assert isinstance(output, BlockReadOutput)


class TestOrderPreservation:
    """Locks the exact `_read_blocks` output order so the iterative rewrite
    stays byte-compatible with the original recursive traversal."""

    def test_block_order_and_child_page_mapping(self) -> None:
        connector = NotionConnector()

        # page-1
        #  ├─ toggle (text "Toggle Title") ── inner (text "Inner")
        #  ├─ child_page "sub-page-1"
        #  └─ paragraph (text "Sibling")
        responses: dict[str, dict[str, Any]] = {
            "page-1": {
                "results": [
                    {
                        "id": "toggle-1",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": "Toggle Title"}}]
                        },
                        "has_children": True,
                    },
                    {
                        "id": "sub-page-1",
                        "type": "child_page",
                        "child_page": {"title": "Sub"},
                        "has_children": True,
                    },
                    {
                        "id": "para-1",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": "Sibling"}}]},
                        "has_children": False,
                    },
                ],
                "next_cursor": None,
            },
            "toggle-1": {
                "results": [
                    {
                        "id": "inner-1",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": "Inner"}}]},
                        "has_children": False,
                    }
                ],
                "next_cursor": None,
            },
        }

        def fetch(block_id: str, _cursor: str | None = None) -> dict[str, Any]:
            # KeyError here means the connector fetched a block it shouldn't have
            # (e.g. a child_page or a leaf) — a regression worth failing on.
            return responses[block_id]

        with patch.object(connector, "_fetch_child_blocks", side_effect=fetch):
            output = connector._read_blocks("page-1")

        # Descendants emit before their parent's own text; siblings in order.
        assert [b.text for b in output.blocks] == ["Inner", "Toggle Title", "Sibling"]
        # Child pages are collected (not inlined) and mapped to the containing page.
        assert output.child_page_ids == ["sub-page-1"]
        assert connector._child_page_parent_map["sub-page-1"] == "page-1"
