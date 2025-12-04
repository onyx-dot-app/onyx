"""
Unit tests for CodaParser.

Tests all static methods of the CodaParser class including:
- Timestamp parsing
- Page hierarchy navigation
- Cell value formatting
- Table to markdown conversion
- Page title and content building

Run with: pytest test_coda_parser.py -v
"""

from datetime import datetime
from datetime import timezone

import pytest

from onyx.connectors.coda.helpers.parser import CodaParser
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.page import CodaPageReference
from onyx.connectors.coda.models.table import CodaColumn
from onyx.connectors.coda.models.table import CodaColumnFormat
from onyx.connectors.coda.models.table import CodaColumnFormatType
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
from onyx.connectors.coda.models.table import TableType


class TestParseTimestamp:
    """Test suite for parse_timestamp method."""

    def test_parse_iso8601_with_z_suffix(self) -> None:
        """Test parsing ISO 8601 timestamp with Z suffix."""
        timestamp_str = "2024-12-04T12:30:45Z"
        result = CodaParser.parse_timestamp(timestamp_str)

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 4
        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 45

    def test_parse_iso8601_with_utc_offset(self) -> None:
        """Test parsing ISO 8601 timestamp with UTC offset."""
        timestamp_str = "2024-12-04T12:30:45+00:00"
        result = CodaParser.parse_timestamp(timestamp_str)

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_parse_iso8601_with_timezone_conversion(self) -> None:
        """Test that timestamps are converted to UTC."""
        # PST is UTC-8, so 12:00 PST = 20:00 UTC
        timestamp_str = "2024-12-04T12:00:00-08:00"
        result = CodaParser.parse_timestamp(timestamp_str)

        assert result.tzinfo == timezone.utc
        assert result.hour == 20  # Converted to UTC

    def test_parse_iso8601_with_microseconds(self) -> None:
        """Test parsing timestamp with microseconds."""
        timestamp_str = "2024-12-04T12:30:45.123456Z"
        result = CodaParser.parse_timestamp(timestamp_str)

        assert isinstance(result, datetime)
        assert result.microsecond == 123456


class TestGetPagePath:
    """Test suite for get_page_path method."""

    def test_single_page_no_parent(self) -> None:
        """Test path for a page with no parent."""
        page = CodaPage(
            id="page-1",
            name="Root Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/page-1",
            browserLink="https://coda.io/d/doc-1/page-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )
        page_map = {"page-1": page}

        result = CodaParser.get_page_path(page, page_map)
        assert result == "Root Page"

    def test_two_level_hierarchy(self) -> None:
        """Test path for a page with one parent."""
        parent = CodaPage(
            id="parent-1",
            name="Parent Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/parent-1",
            browserLink="https://coda.io/d/doc-1/parent-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )

        child = CodaPage(
            id="child-1",
            name="Child Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/child-1",
            browserLink="https://coda.io/d/doc-1/child-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
            parent=CodaPageReference(
                id="parent-1",
                name="Parent Page",
                href="https://coda.io/apis/v1/docs/doc-1/pages/parent-1",
                browserLink="https://coda.io/d/doc-1/parent-1",
                type=CodaObjectType.PAGE,
            ),
        )

        page_map = {"parent-1": parent, "child-1": child}

        result = CodaParser.get_page_path(child, page_map)
        assert result == "Parent Page / Child Page"

    def test_three_level_hierarchy(self) -> None:
        """Test path for a deeply nested page."""
        grandparent = CodaPage(
            id="grandparent-1",
            name="Grandparent",
            href="https://coda.io/apis/v1/docs/doc-1/pages/grandparent-1",
            browserLink="https://coda.io/d/doc-1/grandparent-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )

        parent = CodaPage(
            id="parent-1",
            name="Parent",
            href="https://coda.io/apis/v1/docs/doc-1/pages/parent-1",
            browserLink="https://coda.io/d/doc-1/parent-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
            parent=CodaPageReference(
                id="grandparent-1",
                name="Grandparent",
                href="https://coda.io/apis/v1/docs/doc-1/pages/grandparent-1",
                browserLink="https://coda.io/d/doc-1/grandparent-1",
                type=CodaObjectType.PAGE,
            ),
        )

        child = CodaPage(
            id="child-1",
            name="Child",
            href="https://coda.io/apis/v1/docs/doc-1/pages/child-1",
            browserLink="https://coda.io/d/doc-1/child-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
            parent=CodaPageReference(
                id="parent-1",
                name="Parent",
                href="https://coda.io/apis/v1/docs/doc-1/pages/parent-1",
                browserLink="https://coda.io/d/doc-1/parent-1",
                type=CodaObjectType.PAGE,
            ),
        )

        page_map = {
            "grandparent-1": grandparent,
            "parent-1": parent,
            "child-1": child,
        }

        result = CodaParser.get_page_path(child, page_map)
        assert result == "Grandparent / Parent / Child"

    def test_missing_parent_in_map(self) -> None:
        """Test path when parent is referenced but not in page_map."""
        child = CodaPage(
            id="child-1",
            name="Child Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/child-1",
            browserLink="https://coda.io/d/doc-1/child-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
            parent=CodaPageReference(
                id="missing-parent",
                name="Missing Parent",
                href="https://coda.io/apis/v1/docs/doc-1/pages/missing-parent",
                browserLink="https://coda.io/d/doc-1/missing-parent",
                type=CodaObjectType.PAGE,
            ),
        )

        page_map = {"child-1": child}

        # Should stop at the child when parent is not found
        result = CodaParser.get_page_path(child, page_map)
        assert result == "Child Page"

    def test_parent_with_no_id(self) -> None:
        """Test path when parent reference has no ID."""
        child = CodaPage(
            id="child-1",
            name="Child Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/child-1",
            browserLink="https://coda.io/d/doc-1/child-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
            parent=CodaPageReference(
                id="",
                name="Empty ID Parent",
                href="https://coda.io/apis/v1/docs/doc-1/pages/empty",
                browserLink="https://coda.io/d/doc-1/empty",
                type=CodaObjectType.PAGE,
            ),
        )

        page_map = {"child-1": child}

        # Should stop when parent ID is empty
        result = CodaParser.get_page_path(child, page_map)
        assert result == "Child Page"


class TestFormatCellValue:
    """Test suite for format_cell_value method."""

    def test_none_value(self) -> None:
        """Test formatting None value."""
        result = CodaParser.format_cell_value(None)
        assert result == ""

    def test_empty_string(self) -> None:
        """Test formatting empty string."""
        result = CodaParser.format_cell_value("")
        assert result == ""

    def test_dict_with_name(self) -> None:
        """Test formatting dict with 'name' key."""
        value = {"name": "John Doe", "email": "john@example.com"}
        result = CodaParser.format_cell_value(value)
        assert result == "John Doe"

    def test_dict_with_url(self) -> None:
        """Test formatting dict with 'url' key."""
        value = {"url": "https://example.com", "title": "Example"}
        result = CodaParser.format_cell_value(value)
        assert result == "https://example.com"

    def test_dict_without_name_or_url(self) -> None:
        """Test formatting dict without special keys."""
        value = {"key1": "value1", "key2": "value2"}
        result = CodaParser.format_cell_value(value)
        assert "key1" in result or "value1" in result

    def test_list_of_strings(self) -> None:
        """Test formatting list of strings."""
        value = ["Apple", "Banana", "Cherry"]
        result = CodaParser.format_cell_value(value)
        assert result == "Apple, Banana, Cherry"

    def test_list_of_numbers(self) -> None:
        """Test formatting list of numbers."""
        value = [1, 2, 3, 4, 5]
        result = CodaParser.format_cell_value(value)
        assert result == "1, 2, 3, 4, 5"

    def test_empty_list(self) -> None:
        """Test formatting empty list."""
        value: list[str] = []
        result = CodaParser.format_cell_value(value)
        assert result == ""

    def test_boolean_true(self) -> None:
        """Test formatting True boolean."""
        result = CodaParser.format_cell_value(True)
        assert result == "✓"

    def test_boolean_false(self) -> None:
        """Test formatting False boolean."""
        result = CodaParser.format_cell_value(False)
        assert result == ""

    def test_string_with_pipe_character(self) -> None:
        """Test that pipe characters are escaped for markdown tables."""
        value = "Column A | Column B"
        result = CodaParser.format_cell_value(value)
        assert result == "Column A \\| Column B"

    def test_string_with_newline(self) -> None:
        """Test that newlines are replaced with spaces."""
        value = "Line 1\nLine 2\nLine 3"
        result = CodaParser.format_cell_value(value)
        assert result == "Line 1 Line 2 Line 3"

    def test_string_with_both_pipe_and_newline(self) -> None:
        """Test string with both pipe and newline characters."""
        value = "A | B\nC | D"
        result = CodaParser.format_cell_value(value)
        assert result == "A \\| B C \\| D"

    def test_number_value(self) -> None:
        """Test formatting number value."""
        result = CodaParser.format_cell_value(42)
        assert result == "42"

    def test_float_value(self) -> None:
        """Test formatting float value."""
        result = CodaParser.format_cell_value(3.14159)
        assert result == "3.14159"


class TestConvertTableToMarkdown:
    """Test suite for convert_table_to_markdown method."""

    def test_normal_table_with_data(self) -> None:
        """Test converting a normal table with columns and rows."""
        table = CodaTableReference(
            id="table-1",
            name="Test Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns = [
            CodaColumn(
                id="col-1",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-1",
                name="Name",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=True,
            ),
            CodaColumn(
                id="col-2",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-2",
                name="Age",
                format=CodaColumnFormat(
                    type=CodaColumnFormatType.number, isArray=False
                ),
                display=True,
            ),
        ]

        rows = [
            CodaRow(
                id="row-1",
                name="Row 1",
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/rows/row-1",
                type=CodaObjectType.ROW,
                index=0,
                browserLink="https://coda.io/d/doc-1/table-1/row-1",
                createdAt="2024-01-01T00:00:00Z",
                updatedAt="2024-01-01T00:00:00Z",
                values={"col-1": "Alice", "col-2": 30},
            ),
            CodaRow(
                id="row-2",
                name="Row 2",
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/rows/row-2",
                type=CodaObjectType.ROW,
                index=1,
                browserLink="https://coda.io/d/doc-1/table-1/row-2",
                createdAt="2024-01-01T00:00:00Z",
                updatedAt="2024-01-01T00:00:00Z",
                values={"col-1": "Bob", "col-2": 25},
            ),
        ]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        # Verify structure
        assert "# Test Table" in result
        assert "| Name | Age |" in result
        assert "| --- | --- |" in result
        assert "| Alice | 30 |" in result
        assert "| Bob | 25 |" in result

    def test_empty_table_no_columns(self) -> None:
        """Test converting a table with no columns."""
        table = CodaTableReference(
            id="table-1",
            name="Empty Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns: list[CodaColumn] = []
        rows: list[CodaRow] = []

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Empty Table" in result
        assert "*Empty table - no columns defined*" in result

    def test_empty_table_no_rows(self) -> None:
        """Test converting a table with columns but no rows."""
        table = CodaTableReference(
            id="table-1",
            name="Empty Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns = [
            CodaColumn(
                id="col-1",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-1",
                name="Name",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=True,
            ),
        ]

        rows: list[CodaRow] = []

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Empty Table" in result
        assert "*Empty table - no data*" in result

    def test_no_displayable_columns(self) -> None:
        """Test converting a table where all columns have display=False."""
        table = CodaTableReference(
            id="table-1",
            name="Hidden Columns Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns = [
            CodaColumn(
                id="col-1",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-1",
                name="Hidden Column",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=False,
            ),
        ]

        rows = [
            CodaRow(
                id="row-1",
                name="Row 1",
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/rows/row-1",
                type=CodaObjectType.ROW,
                index=0,
                browserLink="https://coda.io/d/doc-1/table-1/row-1",
                createdAt="2024-01-01T00:00:00Z",
                updatedAt="2024-01-01T00:00:00Z",
                values={"col-1": "Data"},
            ),
        ]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Hidden Columns Table" in result
        assert "*No displayable columns*" in result

    def test_mixed_displayable_columns(self) -> None:
        """Test that only displayable columns are included."""
        table = CodaTableReference(
            id="table-1",
            name="Mixed Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns = [
            CodaColumn(
                id="col-1",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-1",
                name="Visible",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=True,
            ),
            CodaColumn(
                id="col-2",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-2",
                name="Hidden",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=False,
            ),
            CodaColumn(
                id="col-3",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-3",
                name="Also Visible",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=True,
            ),
        ]

        rows = [
            CodaRow(
                id="row-1",
                name="Row 1",
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/rows/row-1",
                type=CodaObjectType.ROW,
                index=0,
                browserLink="https://coda.io/d/doc-1/table-1/row-1",
                createdAt="2024-01-01T00:00:00Z",
                updatedAt="2024-01-01T00:00:00Z",
                values={"col-1": "A", "col-2": "B", "col-3": "C"},
            ),
        ]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        # Should only include visible columns
        assert "| Visible | Also Visible |" in result
        assert "Hidden" not in result
        assert "| A | C |" in result

    def test_missing_cell_values(self) -> None:
        """Test handling rows with missing cell values."""
        table = CodaTableReference(
            id="table-1",
            name="Sparse Table",
            href="https://coda.io/apis/v1/docs/doc-1/tables/table-1",
            browserLink="https://coda.io/d/doc-1/table-1",
            type=CodaObjectType.TABLE,
            tableType=TableType.TABLE,
        )

        columns = [
            CodaColumn(
                id="col-1",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-1",
                name="Name",
                format=CodaColumnFormat(type=CodaColumnFormatType.text, isArray=False),
                display=True,
            ),
            CodaColumn(
                id="col-2",
                type=CodaObjectType.COLUMN,
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/columns/col-2",
                name="Age",
                format=CodaColumnFormat(
                    type=CodaColumnFormatType.number, isArray=False
                ),
                display=True,
            ),
        ]

        rows = [
            CodaRow(
                id="row-1",
                name="Row 1",
                href="https://coda.io/apis/v1/docs/doc-1/tables/table-1/rows/row-1",
                type=CodaObjectType.ROW,
                index=0,
                browserLink="https://coda.io/d/doc-1/table-1/row-1",
                createdAt="2024-01-01T00:00:00Z",
                updatedAt="2024-01-01T00:00:00Z",
                values={"col-1": "Alice"},  # Missing col-2
            ),
        ]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        # Should handle missing values gracefully
        assert "| Name | Age |" in result
        assert "| Alice |  |" in result


class TestBuildPageTitle:
    """Test suite for build_page_title method."""

    def test_page_with_name_only(self) -> None:
        """Test building title for page with name only."""
        page = CodaPage(
            id="page-1",
            name="My Page",
            href="https://coda.io/apis/v1/docs/doc-1/pages/page-1",
            browserLink="https://coda.io/d/doc-1/page-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )

        result = CodaParser.build_page_title(page)
        assert result == "My Page"

    def test_page_with_name_and_subtitle(self) -> None:
        """Test building title for page with name and subtitle."""
        page = CodaPage(
            id="page-1",
            name="My Page",
            subtitle="A detailed description",
            href="https://coda.io/apis/v1/docs/doc-1/pages/page-1",
            browserLink="https://coda.io/d/doc-1/page-1",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )

        result = CodaParser.build_page_title(page)
        assert result == "My Page - A detailed description"

    def test_page_with_empty_name(self) -> None:
        """Test building title for page with empty name."""
        page = CodaPage(
            id="page-456",
            name="",
            href="https://coda.io/apis/v1/docs/doc-1/pages/page-456",
            browserLink="https://coda.io/d/doc-1/page-456",
            type=CodaObjectType.PAGE,
            isHidden=False,
            isEffectivelyHidden=False,
            children=[],
            contentType="canvas",
        )

        result = CodaParser.build_page_title(page)
        assert result == "Untitled Page page-456"


class TestBuildPageContent:
    """Test suite for build_page_content method."""

    def test_combines_title_and_content(self) -> None:
        """Test that title and content are combined correctly."""
        title = "My Page Title"
        content = "This is the page content.\n\nWith multiple paragraphs."

        result = CodaParser.build_page_content(title, content)

        assert result.startswith("My Page Title\n\n")
        assert "This is the page content." in result
        assert "With multiple paragraphs." in result

    def test_empty_content(self) -> None:
        """Test with empty content."""
        title = "My Page Title"
        content = ""

        result = CodaParser.build_page_content(title, content)

        assert result == "My Page Title\n\n"

    def test_preserves_markdown_formatting(self) -> None:
        """Test that markdown formatting is preserved."""
        title = "Documentation"
        content = "# Header\n\n**Bold text** and *italic text*"

        result = CodaParser.build_page_content(title, content)

        assert "# Header" in result
        assert "**Bold text**" in result
        assert "*italic text*" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
