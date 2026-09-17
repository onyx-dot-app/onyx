import json
import os
from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.gitbook.connector import (
    GitbookApiClient,
    _convert_page_to_document,
    _extract_text_from_document,
)


def _load_fixture() -> dict[str, Any]:
    json_path = os.path.join(os.path.dirname(__file__), "parser_coverage_page.json")
    with open(json_path, "r") as f:
        return json.load(f)


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "nodes": [{"object": "text", "leaves": [{"object": "leaf", "text": text}]}],
    }


def _list(list_type: str, items: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": list_type,
        "nodes": [
            {"object": "block", "type": "list-item", "nodes": item} for item in items
        ],
    }


def _document(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"document": {"nodes": nodes}}


def test_parser_coverage_fixture() -> None:
    """Real API response that exercises every supported block type."""
    text = _extract_text_from_document(_load_fixture())

    # ordered lists, including nesting
    assert "1. Create a parser fixture." in text
    assert "* This nested list item has bold text." in text
    assert "1. This ordered item is nested twice." in text

    # blockquote keeps non-paragraph children
    assert '> print("quoted code must remain")' in text
    assert "> * A quoted list must also remain." in text

    # GitBook-specific containers
    assert "This callout includes an important parsing warning." in text
    assert 'console.log("tab content");' in text
    assert 'print("tab content")' in text
    assert "This hidden detail must remain available to the parser." in text
    assert "Column text remains indexed." in text
    assert "This is the second column." in text

    # void blocks with data payloads
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in text
    assert "E = mc^2" in text

    # image caption and inline links (text and URL)
    assert "A blue placeholder image" in text
    assert (
        "[Download the parser fixture](https://example.com/parser-fixture.pdf)" in text
    )
    assert "[documentation link](https://example.com/docs)" in text

    # table with a text fragment cell
    assert "| Fixture card | Target |" in text
    assert "A card description" in text


def test_table_cell_with_lists() -> None:
    """Cells whose fragments hold lists must render, not come out empty."""
    table = {
        "object": "block",
        "type": "table",
        "data": {
            "records": {
                "rec1": {"orderIndex": "a0", "values": {"col1": "frag1"}},
            },
            "definition": {"col1": {"id": "col1", "title": "Steps", "type": "text"}},
            "view": {"columns": ["col1"]},
        },
        "fragments": [
            {
                "object": "fragment",
                "fragment": "frag1",
                "type": "table-cell",
                "nodes": [
                    _list(
                        "list-unordered",
                        [[_paragraph("first step")], [_paragraph("second step")]],
                    ),
                    _list("list-ordered", [[_paragraph("numbered step")]]),
                ],
            }
        ],
    }

    text = _extract_text_from_document(_document([table]))

    assert "| Steps |" in text
    assert "* first step<br>* second step" in text
    assert "1. numbered step" in text
    # the cell must stay on one table row
    assert "\n* first step" not in text


def test_table_non_text_cell_values() -> None:
    """Non-fragment cell values (bools, numbers, refs) must not break the row."""
    table = {
        "object": "block",
        "type": "table",
        "data": {
            "records": {
                "rec1": {
                    "orderIndex": "a0",
                    "values": {
                        "done": True,
                        "count": 3,
                        "target": {"kind": "page", "page": "abc"},
                        "link": {"kind": "url", "url": "https://example.com"},
                    },
                },
            },
            "definition": {
                "done": {"title": "Done", "type": "checkbox"},
                "count": {"title": "Count", "type": "number"},
                "target": {"title": "Target", "type": "content-ref"},
                "link": {"title": "Link", "type": "content-ref"},
            },
            "view": {"columns": ["done", "count", "target", "link"]},
        },
        "fragments": [],
    }

    text = _extract_text_from_document(_document([table]))

    assert "| true | 3 |  | https://example.com |" in text


def test_table_malformed_records_and_unresolved_fragment_ids() -> None:
    """Non-dict records must not crash the sort; unresolved fragment ids must
    not leak into indexed text, whatever the column type says."""
    table = {
        "object": "block",
        "type": "table",
        "data": {
            "records": {
                "bad": "not-a-dict",
                "bad-values": {"orderIndex": "a1", "values": "not-a-mapping"},
                "rec1": {
                    "orderIndex": "a0",
                    "values": {"col1": "frag1", "col2": "missing-fragment-id"},
                },
            },
            "definition": {
                "col1": {"title": "Known", "type": "text"},
                "col2": {"title": "Unknown", "type": "some-future-type"},
            },
            "view": {"columns": ["col1", "col2"]},
        },
        "fragments": [
            {
                "object": "fragment",
                "fragment": "frag1",
                "type": "table-cell",
                "nodes": [_paragraph("resolved cell")],
            }
        ],
    }

    text = _extract_text_from_document(_document([table]))

    assert "| resolved cell |  |" in text
    assert "missing-fragment-id" not in text
    assert "not-a-dict" not in text
    assert "not-a-mapping" not in text


def test_empty_heading_renders_nothing() -> None:
    doc = _document(
        [
            {
                "object": "block",
                "type": "heading-1",
                "nodes": [
                    {"object": "text", "leaves": [{"object": "leaf", "text": ""}]}
                ],
            },
            _paragraph("body"),
        ]
    )

    text = _extract_text_from_document(doc)

    assert "#" not in text
    assert "body" in text


def test_empty_list_item_does_not_raise() -> None:
    doc = _document(
        [
            _list("list-unordered", [[_paragraph("real item")], []]),
            _list("list-tasks", [[]]),
        ]
    )

    text = _extract_text_from_document(doc)

    assert "* real item" in text
    assert "- [ ]" in text


def test_unknown_block_type_falls_back_to_children() -> None:
    doc = _document(
        [
            {
                "object": "block",
                "type": "some-future-block",
                "nodes": [_paragraph("must not disappear")],
                "fragments": [
                    {
                        "object": "fragment",
                        "fragment": "extra",
                        "nodes": [_paragraph("fragment text kept")],
                    }
                ],
            }
        ]
    )

    text = _extract_text_from_document(doc)

    assert "must not disappear" in text
    assert "fragment text kept" in text


def test_page_description_prepended_once() -> None:
    client = MagicMock(spec=GitbookApiClient)
    client.get_page_content.return_value = _document([_paragraph("body text")])
    page = {
        "id": "page1",
        "title": "Titled page",
        "description": "A short description",
    }

    document = _convert_page_to_document(client, "space1", page)

    text = document.sections[0].text
    assert text is not None
    assert text.startswith("A short description\n\nbody text")
    assert text.count("A short description") == 1

    # no description -> body only, no stray separator
    client.get_page_content.return_value = _document([_paragraph("body text")])
    bare = _convert_page_to_document(client, "space1", {"id": "page2", "title": "T"})
    assert bare.sections[0].text is not None
    assert bare.sections[0].text.startswith("body text")


def test_legacy_formats_unchanged() -> None:
    """Shapes the daily connector test relies on must keep rendering the same."""
    doc = _document(
        [
            {
                "object": "block",
                "type": "heading-2",
                "nodes": [
                    {"object": "text", "leaves": [{"object": "leaf", "text": "Title"}]}
                ],
            },
            _list("list-unordered", [[_paragraph("Fruit Shopping List:")]]),
            {
                "object": "block",
                "type": "list-tasks",
                "nodes": [
                    {
                        "object": "block",
                        "type": "list-item",
                        "data": {"checked": True},
                        "nodes": [_paragraph("Completed Task")],
                    }
                ],
            },
            {
                "object": "block",
                "type": "blockquote",
                "nodes": [_paragraph("test quote")],
            },
        ]
    )

    text = _extract_text_from_document(doc)

    assert "## Title" in text
    assert "* Fruit Shopping List:" in text
    assert "- [x] Completed Task" in text
    assert "> test quote" in text
