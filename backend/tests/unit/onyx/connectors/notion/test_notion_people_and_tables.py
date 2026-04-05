"""Unit tests for Notion connector handling of people properties and table blocks.

Reproduces two bugs:
1. ENG-3970: People-type database properties (user mentions) are not extracted —
   the user's "name" field is lost when _recurse_properties drills into the
   "person" sub-dict.
2. ENG-3971: Inline table blocks (table/table_row) are not indexed — table_row
   blocks store content in "cells" rather than "rich_text", so no text is extracted.
"""

from unittest.mock import patch

from onyx.connectors.notion.connector import NotionConnector


def _make_connector() -> NotionConnector:
    connector = NotionConnector()
    connector.load_credentials({"notion_integration_token": "fake-token"})
    return connector


class TestPeoplePropertyExtraction:
    """ENG-3970: Verifies that 'people' type database properties extract user names."""

    def test_single_person_property(self) -> None:
        """A database cell with a single @mention should extract the user name."""
        properties = {
            "Team Lead": {
                "id": "abc",
                "type": "people",
                "people": [
                    {
                        "object": "user",
                        "id": "user-uuid-1",
                        "name": "Arturo Martinez",
                        "type": "person",
                        "person": {"email": "arturo@example.com"},
                    }
                ],
            }
        }
        result = NotionConnector._properties_to_str(properties)
        assert (
            "Arturo Martinez" in result
        ), f"Expected 'Arturo Martinez' in extracted text, got: {result!r}"

    def test_multiple_people_property(self) -> None:
        """A database cell with multiple @mentions should extract all user names."""
        properties = {
            "Members": {
                "id": "def",
                "type": "people",
                "people": [
                    {
                        "object": "user",
                        "id": "user-uuid-1",
                        "name": "Arturo Martinez",
                        "type": "person",
                        "person": {"email": "arturo@example.com"},
                    },
                    {
                        "object": "user",
                        "id": "user-uuid-2",
                        "name": "Jane Smith",
                        "type": "person",
                        "person": {"email": "jane@example.com"},
                    },
                ],
            }
        }
        result = NotionConnector._properties_to_str(properties)
        assert (
            "Arturo Martinez" in result
        ), f"Expected 'Arturo Martinez' in extracted text, got: {result!r}"
        assert (
            "Jane Smith" in result
        ), f"Expected 'Jane Smith' in extracted text, got: {result!r}"

    def test_bot_user_property(self) -> None:
        """Bot users (integrations) have 'type': 'bot' — name should still be extracted."""
        properties = {
            "Created By": {
                "id": "ghi",
                "type": "people",
                "people": [
                    {
                        "object": "user",
                        "id": "bot-uuid-1",
                        "name": "Onyx Integration",
                        "type": "bot",
                        "bot": {},
                    }
                ],
            }
        }
        result = NotionConnector._properties_to_str(properties)
        assert (
            "Onyx Integration" in result
        ), f"Expected 'Onyx Integration' in extracted text, got: {result!r}"

    def test_person_without_person_details(self) -> None:
        """Some user objects may have an empty/null person sub-dict."""
        properties = {
            "Assignee": {
                "id": "jkl",
                "type": "people",
                "people": [
                    {
                        "object": "user",
                        "id": "user-uuid-3",
                        "name": "Ghost User",
                        "type": "person",
                        "person": {},
                    }
                ],
            }
        }
        result = NotionConnector._properties_to_str(properties)
        assert (
            "Ghost User" in result
        ), f"Expected 'Ghost User' in extracted text, got: {result!r}"

    def test_people_mixed_with_other_properties(self) -> None:
        """People property should work alongside other property types."""
        properties = {
            "Name": {
                "id": "aaa",
                "type": "title",
                "title": [
                    {
                        "plain_text": "Project Alpha",
                        "type": "text",
                        "text": {"content": "Project Alpha"},
                    }
                ],
            },
            "Lead": {
                "id": "bbb",
                "type": "people",
                "people": [
                    {
                        "object": "user",
                        "id": "user-uuid-1",
                        "name": "Arturo Martinez",
                        "type": "person",
                        "person": {"email": "arturo@example.com"},
                    }
                ],
            },
            "Status": {
                "id": "ccc",
                "type": "status",
                "status": {"name": "In Progress", "id": "status-1"},
            },
        }
        result = NotionConnector._properties_to_str(properties)
        assert "Arturo Martinez" in result
        assert "In Progress" in result


class TestTableBlockExtraction:
    """ENG-3971: Verifies that inline table blocks (table/table_row) are indexed."""

    def _make_blocks_response(self, results: list) -> dict:
        return {"results": results, "next_cursor": None}

    def test_table_row_cells_are_extracted(self) -> None:
        """table_row blocks store content in 'cells', not 'rich_text'.
        The connector should extract text from cells."""
        connector = _make_connector()
        connector.workspace_id = "ws-1"

        table_block = {
            "id": "table-block-1",
            "type": "table",
            "table": {
                "has_column_header": True,
                "has_row_header": False,
                "table_width": 3,
            },
            "has_children": True,
        }

        header_row = {
            "id": "row-1",
            "type": "table_row",
            "table_row": {
                "cells": [
                    [
                        {
                            "type": "text",
                            "text": {"content": "Name"},
                            "plain_text": "Name",
                        }
                    ],
                    [
                        {
                            "type": "text",
                            "text": {"content": "Role"},
                            "plain_text": "Role",
                        }
                    ],
                    [
                        {
                            "type": "text",
                            "text": {"content": "Team"},
                            "plain_text": "Team",
                        }
                    ],
                ]
            },
            "has_children": False,
        }

        data_row = {
            "id": "row-2",
            "type": "table_row",
            "table_row": {
                "cells": [
                    [
                        {
                            "type": "text",
                            "text": {"content": "Arturo Martinez"},
                            "plain_text": "Arturo Martinez",
                        }
                    ],
                    [
                        {
                            "type": "text",
                            "text": {"content": "Engineer"},
                            "plain_text": "Engineer",
                        }
                    ],
                    [
                        {
                            "type": "text",
                            "text": {"content": "Platform"},
                            "plain_text": "Platform",
                        }
                    ],
                ]
            },
            "has_children": False,
        }

        with patch.object(
            connector,
            "_fetch_child_blocks",
            side_effect=[
                self._make_blocks_response([table_block]),
                self._make_blocks_response([header_row, data_row]),
            ],
        ):
            output = connector._read_blocks("page-1")

        all_text = " ".join(block.text for block in output.blocks)
        assert "Arturo Martinez" in all_text, (
            f"Expected 'Arturo Martinez' in table row text, got blocks: "
            f"{[(b.id, b.text) for b in output.blocks]}"
        )
        assert "Engineer" in all_text, (
            f"Expected 'Engineer' in table row text, got blocks: "
            f"{[(b.id, b.text) for b in output.blocks]}"
        )
        assert "Platform" in all_text, (
            f"Expected 'Platform' in table row text, got blocks: "
            f"{[(b.id, b.text) for b in output.blocks]}"
        )

    def test_table_with_empty_cells(self) -> None:
        """Table rows with some empty cells should still extract non-empty content."""
        connector = _make_connector()
        connector.workspace_id = "ws-1"

        table_block = {
            "id": "table-block-2",
            "type": "table",
            "table": {
                "has_column_header": False,
                "has_row_header": False,
                "table_width": 2,
            },
            "has_children": True,
        }

        row_with_empty = {
            "id": "row-3",
            "type": "table_row",
            "table_row": {
                "cells": [
                    [
                        {
                            "type": "text",
                            "text": {"content": "Has Value"},
                            "plain_text": "Has Value",
                        }
                    ],
                    [],  # empty cell
                ]
            },
            "has_children": False,
        }

        with patch.object(
            connector,
            "_fetch_child_blocks",
            side_effect=[
                self._make_blocks_response([table_block]),
                self._make_blocks_response([row_with_empty]),
            ],
        ):
            output = connector._read_blocks("page-2")

        all_text = " ".join(block.text for block in output.blocks)
        assert "Has Value" in all_text, (
            f"Expected 'Has Value' in table row text, got blocks: "
            f"{[(b.id, b.text) for b in output.blocks]}"
        )
