from onyx.connectors.coda.helpers.table_converter import CodaTableConverter
from onyx.connectors.coda.models.table.row import CodaRow


class TestCodaTableConverter:
    def test_extract_cell_value_simple(self):
        """Test extraction of simple scalar values."""
        assert CodaTableConverter.extract_cell_value(None) is None
        assert CodaTableConverter.extract_cell_value("text") == "text"
        assert CodaTableConverter.extract_cell_value(123) == 123
        assert CodaTableConverter.extract_cell_value(12.34) == 12.34
        assert CodaTableConverter.extract_cell_value(True) is True
        assert CodaTableConverter.extract_cell_value(False) is False

    def test_extract_cell_value_list(self):
        """Test extraction of list values."""
        input_list = ["a", 1, True]
        assert CodaTableConverter.extract_cell_value(input_list) == ["a", 1, True]

        # Nested list with None
        input_list_with_none = ["a", None]
        assert CodaTableConverter.extract_cell_value(input_list_with_none) == [
            "a",
            None,
        ]

    def test_extract_cell_value_rich_objects_dict(self):
        """Test extraction from dict-based rich objects (simulating API response structure)."""
        # Currency
        currency = {"@type": "MonetaryAmount", "currency": "USD", "amount": 100.50}
        assert "Type: MonetaryAmount" in CodaTableConverter.extract_cell_value(currency)
        assert "USD" in CodaTableConverter.extract_cell_value(currency)

        # Image
        image = {
            "@type": "ImageObject",
            "url": "http://example.com/img.png",
            "name": "img.png",
            "status": "live",
        }
        extracted_image = CodaTableConverter.extract_cell_value(image)
        assert "Type: ImageObject" in extracted_image
        assert "http://example.com/img.png" in extracted_image

        # Person
        person = {"@type": "Person", "name": "John Doe", "email": "john@example.com"}
        extracted_person = CodaTableConverter.extract_cell_value(person)
        assert "Type: Person" in extracted_person
        assert "John Doe" in extracted_person

        # WebPage
        webpage = {"@type": "WebPage", "url": "http://example.com", "name": "Example"}
        extracted_webpage = CodaTableConverter.extract_cell_value(webpage)
        assert "Type: WebPage" in extracted_webpage
        assert "http://example.com" in extracted_webpage

        # StructuredValue (Row Reference)
        structured = {
            "@type": "StructuredValue",
            "name": "Row Name",
            "url": "http://coda.io/row",
            "table_id": "table-1",
            "row_id": "row-1",
        }
        extracted_structured = CodaTableConverter.extract_cell_value(structured)
        assert "Type: StructuredValue" in extracted_structured
        assert "Row Name" in extracted_structured

    def test_extract_display_value(self):
        """Test conversion to display strings."""
        assert CodaTableConverter.extract_display_value(None) == ""
        assert CodaTableConverter.extract_display_value("test") == "test"
        assert CodaTableConverter.extract_display_value(123) == "123"

        # Test list display
        assert CodaTableConverter.extract_display_value(["a", "b"]) == "a, b"

        # Test rich value display
        person = {"@type": "Person", "name": "Bob", "email": "bob@example.com"}
        display = CodaTableConverter.extract_display_value(person)
        assert "Type: Person" in display
        assert "Bob" in display

    def test_rows_to_dataframe_empty(self):
        """Test conversion of empty list."""
        df = CodaTableConverter.rows_to_dataframe([])
        assert df.empty

    def test_rows_to_dataframe_basic(self):
        """Test basic row conversion."""
        row1 = CodaRow(
            id="row-1",
            index=1,
            name="row-2",
            href="http://end",
            type="row",
            browserLink="http://start",
            createdAt="2024-01-01T00:00:00Z",
            updatedAt="2024-01-02T00:00:00Z",
            values={"col1": "val1", "col2": 2},
            parent={
                "href": "http://start",
                "browserLink": "http://start",
                "id": "table-1",
                "type": "table",
                "name": "Table 1",
                "tableType": "table",
            },
        )
        row2 = CodaRow(
            id="row-2",
            index=2,
            name="row-2",
            href="http://end",
            type="row",
            browserLink="http://start",
            createdAt="2024-01-03T00:00:00Z",
            updatedAt="2024-01-04T00:00:00Z",
            values={"col1": "val3", "col2": 4},
            parent={
                "href": "http://start",
                "browserLink": "http://start",
                "id": "table-1",
                "type": "table",
                "name": "Table 1",
                "tableType": "table",
            },
        )

        df = CodaTableConverter.rows_to_dataframe([row1, row2])

        assert len(df) == 2
        assert "_row_id" in df.columns
        assert "_created_at" in df.columns
        assert "col1" in df.columns
        assert df.iloc[0]["col1"] == "val1"
        assert df.iloc[1]["col1"] == "val3"

    def test_rows_to_dataframe_no_metadata(self):
        """Test conversion without metadata columns."""
        row1 = CodaRow(
            id="row-1",
            index=1,
            name="row-2",
            href="http://end",
            type="row",
            browserLink="http://start",
            createdAt="2024-01-01",
            updatedAt="2024-01-01",
            values={"col1": "val3", "col2": 4},
            parent={
                "href": "http://start",
                "browserLink": "http://start",
                "id": "table-1",
                "type": "table",
                "name": "Table 1",
                "tableType": "table",
            },
        )

        df = CodaTableConverter.rows_to_dataframe([row1], include_metadata=False)

        assert "_row_id" not in df.columns
        assert "col1" in df.columns
        assert "col2" in df.columns
        assert len(df.columns) == 2

    def test_rows_to_formats(self):
        """Test export to different formats."""
        row1 = CodaRow(
            id="row-1",
            index=1,
            name="row-2",
            href="http://end",
            type="row",
            browserLink="http://start",
            createdAt="2024-01-01",
            updatedAt="2024-01-01",
            values={"col1": "val1"},
            parent={
                "href": "http://start",
                "browserLink": "http://start",
                "id": "table-1",
                "type": "table",
                "name": "Table 1",
                "tableType": "table",
            },
        )

        # Test specific formats
        formats = ["JSON", "CSV"]
        eval_df = CodaTableConverter.rows_to_formats([row1], formats=formats)

        assert len(eval_df) == 2
        assert set(eval_df["Data Format"]) == {"JSON", "CSV"}

        # Test all formats (default)
        eval_df_all = CodaTableConverter.rows_to_formats([row1])
        assert len(eval_df_all) >= 5  # Should have JSON, CSV, HTML, etc.
