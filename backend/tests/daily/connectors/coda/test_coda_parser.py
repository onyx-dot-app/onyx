from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock

from onyx.connectors.coda.helpers.parser import CodaParser
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from tests.daily.connectors.coda.conftest import make_column
from tests.daily.connectors.coda.conftest import make_doc
from tests.daily.connectors.coda.conftest import make_page
from tests.daily.connectors.coda.conftest import make_page_ref
from tests.daily.connectors.coda.conftest import make_row
from tests.daily.connectors.coda.conftest import make_table


class TestCodaParser:
    def test_parse_timestamp(self) -> None:
        """Test parsing of ISO 8601 timestamps."""
        ts = "2023-01-01T12:00:00Z"
        dt = CodaParser.parse_timestamp(ts)
        assert dt == datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Test with offset
        ts_offset = "2023-01-01T12:00:00+01:00"
        dt_offset = CodaParser.parse_timestamp(ts_offset)
        assert dt_offset == datetime(2023, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    def test_get_page_path(self) -> None:
        """Test breadcrumb path construction."""
        root = make_page(id="root", name="Root")

        root_ref = make_page_ref(id="root", name="Root")
        child = make_page(id="child", name="Child", parent=root_ref)

        child_ref = make_page_ref(id="child", name="Child")
        grandchild = make_page(id="grandchild", name="Grandchild", parent=child_ref)

        page_map = {"root": root, "child": child, "grandchild": grandchild}

        assert CodaParser.get_page_path(root, page_map) == "Root"
        assert CodaParser.get_page_path(child, page_map) == "Root / Child"
        assert (
            CodaParser.get_page_path(grandchild, page_map)
            == "Root / Child / Grandchild"
        )

        # Test broken chain
        missing_ref = make_page_ref(id="missing", name="Missing")
        orphan = make_page(id="orphan", name="Orphan", parent=missing_ref)
        assert CodaParser.get_page_path(orphan, page_map) == "Orphan"

    def test_format_cell_value(self) -> None:
        """Test formatting of various cell value types."""
        assert CodaParser.format_cell_value(None) == ""
        assert CodaParser.format_cell_value("") == ""
        assert CodaParser.format_cell_value("text") == "text"
        assert CodaParser.format_cell_value(123) == "123"
        assert CodaParser.format_cell_value(True) == "✓"
        assert CodaParser.format_cell_value(False) == ""
        assert CodaParser.format_cell_value(["a", "b"]) == "a, b"
        assert CodaParser.format_cell_value({"name": "Person"}) == "Person"
        assert (
            CodaParser.format_cell_value({"url": "http://example.com"})
            == "http://example.com"
        )
        assert CodaParser.format_cell_value({"other": "value"}) == "{'other': 'value'}"

        # Test escaping
        assert CodaParser.format_cell_value("a|b") == "a\\|b"
        assert CodaParser.format_cell_value("a\nb") == "a b"

    def test_convert_table_to_text(self) -> None:
        """Test table to text conversion."""
        table = make_table(name="My Table")

        # Case 1: Empty columns
        assert "Empty table - no columns defined" in CodaParser.convert_table_to_text(
            table, [], []
        )

        # Case 2: Empty rows
        cols = [make_column(id="c1", name="Name")]
        assert "Empty table - no data" in CodaParser.convert_table_to_text(
            table, cols, []
        )

        # Case 3: No displayable columns
        hidden_col = make_column(id="c1", name="Hidden", display=False)
        assert "No displayable columns" in CodaParser.convert_table_to_text(
            table, [hidden_col], [make_row()]
        )

        # Case 4: Normal table
        cols = [
            make_column(id="c1", name="Name"),
            make_column(id="c2", name="Age"),
        ]
        rows = [
            make_row(values={"c1": "Alice", "c2": 30}),
            make_row(values={"c1": "Bob", "c2": 25}),
        ]

        text = CodaParser.convert_table_to_text(table, cols, rows)
        assert "My Table" in text
        assert "Name: Alice" in text
        assert "Age: 30" in text
        assert "Name: Bob" in text
        assert "Age: 25" in text

    def test_build_page_title(self) -> None:
        """Test page title construction."""
        page = make_page(name="My Page")
        assert CodaParser.build_page_title(page) == "My Page"

        page_with_subtitle = make_page(name="My Page", subtitle="Subtitle")
        assert CodaParser.build_page_title(page_with_subtitle) == "My Page - Subtitle"

        untitled = make_page(name="", id="123")
        assert CodaParser.build_page_title(untitled) == "Untitled Page 123"

    def test_parse_html_content(self) -> None:
        """Test HTML content parsing."""
        # Test basic text
        content = "<p>Hello</p><p>World</p>"
        sections = CodaParser.parse_html_content(content)
        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        assert "Hello" in sections[0].text
        assert "World" in sections[0].text

        # Test image
        content = '<img src="http://example.com/img.png" />'
        sections = CodaParser.parse_html_content(content)
        assert len(sections) == 1
        assert isinstance(sections[0], ImageSection)
        assert sections[0].link == "http://example.com/img.png"

        # Test table placeholder
        content = '<table data-coda-grid-id="grid-123"></table>'
        sections = CodaParser.parse_html_content(content)
        assert len(sections) == 1
        assert isinstance(sections[0], TextSection)
        assert sections[0].text == "[[TABLE:grid-123]]"

        # Test mixed content
        content = """
        <h1>Title</h1>
        <p>Text</p>
        <img src="img.png" />
        <table data-coda-grid-id="grid-1"></table>
        """
        sections = CodaParser.parse_html_content(content)
        # Expect: Text(Title\nText), Image, Text([[TABLE:grid-1]])
        # Note: The parser flushes text before image and table
        assert len(sections) == 3
        assert isinstance(sections[0], TextSection)  # Title + Text
        assert isinstance(sections[1], ImageSection)  # Image
        assert isinstance(sections[2], TextSection)  # Table placeholder

    def test_build_page_owners(self) -> None:
        """Test owner extraction."""
        # Test with authors
        author = MagicMock()
        author.name = "Author"
        author.email = "author@example.com"

        creator = MagicMock()
        creator.name = "Creator"
        creator.email = "creator@example.com"

        updater = MagicMock()
        updater.name = "Updater"
        updater.email = "updater@example.com"

        page = make_page()
        page.authors = [author]
        page.createdBy = creator
        page.updatedBy = updater

        primary, secondary = CodaParser.build_page_owners(page)

        assert primary is not None
        assert len(primary) == 1
        assert primary[0].display_name == "Author"

        assert secondary is not None
        assert len(secondary) == 2
        assert secondary[0].display_name == "Creator"
        assert secondary[1].display_name == "Updater"

    def test_build_doc_owners(self) -> None:
        """Test doc owner extraction."""
        doc = make_doc(ownerName="Owner", owner="owner@example.com")
        owners = CodaParser.build_doc_owners(doc)
        assert owners is not None
        assert len(owners) == 1
        assert owners[0].display_name == "Owner"
        assert owners[0].email == "owner@example.com"

    def test_build_page_metadata(self) -> None:
        """Test page metadata generation."""
        doc = make_doc()
        page = make_page(doc_id=doc.id)
        page_map = {page.id: page}

        metadata = CodaParser.build_page_metadata(doc, page, page_map)

        assert metadata["coda_object_type"] == CodaObjectType.PAGE
        assert metadata["doc_id"] == doc.id
        assert metadata["page_id"] == page.id
        assert metadata["page_name"] == page.name
        assert metadata["path"] == page.name

    def test_build_table_metadata(self) -> None:
        """Test table metadata generation."""
        doc = make_doc()
        table = make_table(doc_id=doc.id)
        cols = [make_column()]
        rows = [make_row()]

        metadata = CodaParser.build_table_metadata(
            doc, table, cols, rows, parent_page_id="p1"
        )

        assert metadata["type"] == CodaObjectType.TABLE
        assert metadata["doc_id"] == doc.id
        assert metadata["table_id"] == table.id
        assert metadata["row_count"] == "1"
        assert metadata["column_count"] == "1"
        assert metadata["parent_page_id"] == "p1"
