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
from onyx.connectors.coda.models.icon import CodaIcon
from onyx.connectors.coda.models.page import CodaPageImage
from onyx.connectors.coda.models.person import CodaPersonValue
from onyx.connectors.coda.models.table import CodaColumnFormatType
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from tests.daily.connectors.coda.conftest import make_column
from tests.daily.connectors.coda.conftest import make_doc
from tests.daily.connectors.coda.conftest import make_folder_ref
from tests.daily.connectors.coda.conftest import make_page
from tests.daily.connectors.coda.conftest import make_page_ref
from tests.daily.connectors.coda.conftest import make_row
from tests.daily.connectors.coda.conftest import make_table
from tests.daily.connectors.coda.conftest import make_workspace_ref

# Import factory functions from conftest


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
        page = make_page(id="page-1", name="Root Page")
        page_map = {"page-1": page}

        result = CodaParser.get_page_path(page, page_map)
        assert result == "Root Page"

    def test_two_level_hierarchy(self) -> None:
        """Test path for a page with one parent."""
        parent = make_page(id="parent-1", name="Parent Page")
        child = make_page(
            id="child-1",
            name="Child Page",
            parent=make_page_ref(id="parent-1", name="Parent Page"),
        )

        page_map = {"parent-1": parent, "child-1": child}

        result = CodaParser.get_page_path(child, page_map)
        assert result == "Parent Page / Child Page"

    def test_three_level_hierarchy(self) -> None:
        """Test path for a deeply nested page."""
        grandparent = make_page(id="grandparent-1", name="Grandparent")
        parent = make_page(
            id="parent-1",
            name="Parent",
            parent=make_page_ref(id="grandparent-1", name="Grandparent"),
        )
        child = make_page(
            id="child-1",
            name="Child",
            parent=make_page_ref(id="parent-1", name="Parent"),
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
        child = make_page(
            id="child-1",
            name="Child Page",
            parent=make_page_ref(id="missing-parent", name="Missing Parent"),
        )

        page_map = {"child-1": child}

        # Should stop at the child when parent is not found
        result = CodaParser.get_page_path(child, page_map)
        assert result == "Child Page"

    def test_parent_with_no_id(self) -> None:
        """Test path when parent reference has no ID."""
        child = make_page(
            id="child-1",
            name="Child Page",
            parent=make_page_ref(id="", name="Empty ID Parent"),
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
        table = make_table(id="table-1", name="Test Table")
        columns = [
            make_column(id="col-1", name="Name", format_type=CodaColumnFormatType.text),
            make_column(
                id="col-2", name="Age", format_type=CodaColumnFormatType.number
            ),
        ]
        rows = [
            make_row(id="row-1", index=0, values={"col-1": "Alice", "col-2": 30}),
            make_row(id="row-2", index=1, values={"col-1": "Bob", "col-2": 25}),
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
        table = make_table(id="table-1", name="Empty Table")
        columns = []
        rows = []

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Empty Table" in result
        assert "*Empty table - no columns defined*" in result

    def test_empty_table_no_rows(self) -> None:
        """Test converting a table with columns but no rows."""
        table = make_table(id="table-1", name="Empty Table")
        columns = [make_column(id="col-1", name="Name")]
        rows = []

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Empty Table" in result
        assert "*Empty table - no data*" in result

    def test_no_displayable_columns(self) -> None:
        """Test converting a table where all columns have display=False."""
        table = make_table(id="table-1", name="Hidden Columns Table")
        columns = [make_column(id="col-1", name="Hidden Column", display=False)]
        rows = [make_row(id="row-1", index=0, values={"col-1": "Data"})]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        assert "# Hidden Columns Table" in result
        assert "*No displayable columns*" in result

    def test_mixed_displayable_columns(self) -> None:
        """Test that only displayable columns are included."""
        table = make_table(id="table-1", name="Mixed Table")
        columns = [
            make_column(id="col-1", name="Visible", display=True),
            make_column(id="col-2", name="Hidden", display=False),
            make_column(id="col-3", name="Also Visible", display=True),
        ]
        rows = [
            make_row(
                id="row-1", index=0, values={"col-1": "A", "col-2": "B", "col-3": "C"}
            )
        ]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        # Should only include visible columns
        assert "| Visible | Also Visible |" in result
        assert "Hidden" not in result
        assert "| A | C |" in result

    def test_missing_cell_values(self) -> None:
        """Test handling rows with missing cell values."""
        table = make_table(id="table-1", name="Sparse Table")
        columns = [
            make_column(id="col-1", name="Name"),
            make_column(
                id="col-2", name="Age", format_type=CodaColumnFormatType.number
            ),
        ]
        rows = [make_row(id="row-1", index=0, values={"col-1": "Alice"})]

        result = CodaParser.convert_table_to_markdown(table, columns, rows)

        # Should handle missing values gracefully
        assert "| Name | Age |" in result
        assert "| Alice |  |" in result


class TestBuildPageTitle:
    """Test suite for build_page_title method."""

    def test_page_with_name_only(self) -> None:
        """Test building title for page with name only."""
        page = make_page(id="page-1", name="My Page")

        result = CodaParser.build_page_title(page)
        assert result == "My Page"

    def test_page_with_name_and_subtitle(self) -> None:
        """Test building title for page with name and subtitle."""
        page = make_page(id="page-1", name="My Page", subtitle="A detailed description")

        result = CodaParser.build_page_title(page)
        assert result == "My Page - A detailed description"

    def test_page_with_empty_name(self) -> None:
        """Test building title for page with empty name."""
        page = make_page(id="page-456", name="")

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


class TestBuildPageMetadata:
    """Test suite for build_page_metadata method."""

    def test_basic_page_metadata(self) -> None:
        """Test building metadata for a basic page."""
        doc = make_doc(id="doc-1", name="Test Document")
        page = make_page(id="page-1", name="Test Page")
        page_map = {"page-1": page}

        result = CodaParser.build_page_metadata(doc, page, page_map)

        # Verify required fields
        assert result["coda_object_type"] == CodaObjectType.PAGE
        assert result["doc_name"] == "Test Document"
        assert result["doc_id"] == "doc-1"
        assert result["page_id"] == "page-1"
        assert result["page_name"] == "Test Page"
        assert result["path"] == "Test Page"
        assert result["content_type"] == "canvas"
        assert result["browser_link"] == "https://coda.io/d/doc-1/page-1"

        # Verify optional fields are not present when not provided
        assert "parent_page_id" not in result
        assert "icon" not in result
        assert "subtitle" not in result
        assert "image_url" not in result
        assert "author" not in result

    def test_page_metadata_with_parent(self) -> None:
        """Test building metadata for a page with a parent."""
        doc = make_doc(
            id="doc-1",
            name="Test Document",
            owner="email@s.com",
            ownerName="Test User",
            workspace=make_workspace_ref(id="workspace-1"),
            folder=make_folder_ref(id="folder-1"),
        )
        parent = make_page(id="parent-1", name="Parent Page")
        child = make_page(
            id="child-1",
            name="Child Page",
            parent=make_page_ref(id="parent-1", name="Parent Page"),
        )

        page_map = {"parent-1": parent, "child-1": child}

        result = CodaParser.build_page_metadata(doc, child, page_map)

        # Verify parent is included
        assert result["parent_page_id"] == "parent-1"
        assert result["parent_page_name"] == "Parent Page"
        assert result["path"] == "Parent Page / Child Page"

    def test_page_metadata_comprehensive(self) -> None:
        """Test building metadata with all optional fields populated."""

        doc = make_doc(id="doc-1", name="Test Document")

        # Create child pages
        child1 = make_page_ref(id="child-1", name="Child 1")
        child2 = make_page_ref(id="child-2", name="Child 2")

        page = make_page(
            id="page-1",
            name="Comprehensive Page",
            subtitle="A page with all metadata",
            children=[child1, child2],
            icon=CodaIcon(
                name="rocket", type="icon", browserLink="https://coda.io/icons/rocket"
            ),
            image=CodaPageImage(
                browserLink="https://coda.io/images/page-1.png",
                width=1200,
                height=630,
            ),
            author=CodaPersonValue(
                **{
                    "name": "John Doe",
                    "email": "john@example.com",
                    "@context": "author",
                    "@type": "Person",
                }
            ),
            createdBy=CodaPersonValue(
                **{
                    "name": "Jane Smith",
                    "email": "jane@example.com",
                    "@context": "createdBy",
                    "@type": "Person",
                }
            ),
            updatedBy=CodaPersonValue(
                **{
                    "name": "Bob Wilson",
                    "email": "bob@example.com",
                    "@context": "updatedBy",
                    "@type": "Person",
                }
            ),
            createdAt="2024-01-01T10:00:00Z",
            updatedAt="2024-01-15T14:30:00Z",
        )

        page_map = {"page-1": page}

        result = CodaParser.build_page_metadata(doc, page, page_map)

        # Verify all required fields
        assert result["coda_object_type"] == CodaObjectType.PAGE
        assert result["doc_name"] == "Test Document"
        assert result["doc_id"] == "doc-1"
        assert result["page_id"] == "page-1"
        assert result["page_name"] == "Comprehensive Page"
        assert result["path"] == "Comprehensive Page"
        assert result["content_type"] == "canvas"
        assert result["browser_link"] == "https://coda.io/d/doc-1/page-1"

        # Verify all optional fields
        assert result["subtitle"] == "A page with all metadata"
        assert result["created_at"] == "2024-01-01T10:00:00Z"
        assert result["updated_at"] == "2024-01-15T14:30:00Z"
        assert result["child_count"] == "2"
        assert result["child_page_ids"] == ["child-1", "child-2"]


class TestBuildTableMetadata:
    """Test suite for build_table_metadata method."""

    def test_basic_table_metadata(self) -> None:
        """Test building metadata for a basic table."""
        doc = make_doc(id="doc-1", name="Test Document")
        table = make_table(id="table-1", name="Test Table")
        columns = [
            make_column(id="col-1", name="Name"),
            make_column(
                id="col-2", name="Age", format_type=CodaColumnFormatType.number
            ),
        ]
        rows = [
            make_row(id="row-1", index=0, values={"col-1": "Alice", "col-2": 30}),
            make_row(id="row-2", index=1, values={"col-1": "Bob", "col-2": 25}),
        ]

        result = CodaParser.build_table_metadata(doc, table, columns, rows)

        # Verify all fields
        assert result["type"] == CodaObjectType.TABLE
        assert result["doc_name"] == "Test Document"
        assert result["doc_id"] == "doc-1"
        assert result["table_id"] == "table-1"
        assert result["table_name"] == "Test Table"
        assert result["row_count"] == "2"
        assert result["column_count"] == "2"

    def test_table_metadata_with_no_data(self) -> None:
        """Test building metadata for an empty table."""
        doc = make_doc(id="doc-1", name="Test Document")
        table = make_table(id="table-1", name="Empty Table")
        columns = []
        rows = []

        result = CodaParser.build_table_metadata(doc, table, columns, rows)

        # Verify counts are zero
        assert result["row_count"] == "0"
        assert result["column_count"] == "0"

    def test_table_metadata_with_large_dataset(self) -> None:
        """Test building metadata for a table with many rows."""
        doc = make_doc(id="doc-1", name="Test Document")
        table = make_table(id="table-1", name="Large Table")
        columns = [make_column(id=f"col-{i}", name=f"Column {i}") for i in range(10)]
        rows = [
            make_row(id=f"row-{i}", name=f"Row {i}", index=i, values={})
            for i in range(100)
        ]

        result = CodaParser.build_table_metadata(doc, table, columns, rows)

        # Verify counts
        assert result["row_count"] == "100"
        assert result["column_count"] == "10"


class TestParseHtmlContent:
    """Test suite for parse_html_content method."""

    def test_parse_simple_text(self) -> None:
        """Test parsing simple HTML with text."""
        html = "<p>Hello World</p>"
        sections = CodaParser.parse_html_content(html)

        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        assert sections[0].text == "Hello World"

    def test_parse_text_with_formatting(self) -> None:
        """Test parsing HTML with formatting tags."""
        html = "<p><b>Bold</b> and <i>Italic</i></p>"
        sections = CodaParser.parse_html_content(html)

        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        assert sections[0].text == "Bold and Italic"

    def test_parse_multiple_paragraphs(self) -> None:
        """Test parsing multiple paragraphs."""
        html = "<p>Para 1</p><p>Para 2</p>"
        sections = CodaParser.parse_html_content(html)

        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        # Check that newlines are inserted
        assert "Para 1" in sections[0].text
        assert "Para 2" in sections[0].text
        assert "\n" in sections[0].text

    def test_parse_image_only(self) -> None:
        """Test parsing HTML with only an image."""
        html = '<img src="https://example.com/image.png" />'
        sections = CodaParser.parse_html_content(html)

        assert len(sections) == 1
        assert isinstance(sections[0], ImageSection)
        assert sections[0].link == "https://example.com/image.png"
        assert sections[0].image_file_id == "https://example.com/image.png"

    def test_parse_mixed_content(self) -> None:
        """Test parsing mixed text and images."""
        html = """
        <h1>Title</h1>
        <p>Intro text</p>
        <img src="https://example.com/img1.png" />
        <p>Caption</p>
        """
        sections = CodaParser.parse_html_content(html)

        # Should be: Text (Title + Intro), Image, Text (Caption)
        assert len(sections) == 3
        assert isinstance(sections[0], TextSection)
        assert "Title" in sections[0].text
        assert "Intro text" in sections[0].text

        assert isinstance(sections[1], ImageSection)
        assert sections[1].link == "https://example.com/img1.png"
        assert sections[1].image_file_id == "https://example.com/img1.png"

        assert isinstance(sections[2], TextSection)
        assert "Caption" in sections[2].text

    def test_parse_empty_content(self) -> None:
        """Test parsing empty content."""
        assert CodaParser.parse_html_content("") == []
        assert CodaParser.parse_html_content(None) == []  # type: ignore

    def test_parse_nested_structure(self) -> None:
        """Test parsing nested HTML structure."""
        html = """
        <div>
            <h2>Section 1</h2>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
        </div>
        """
        sections = CodaParser.parse_html_content(html)

        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        text = sections[0].text
        assert "Section 1" in text
        assert "Item 1" in text
        assert "Item 2" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
