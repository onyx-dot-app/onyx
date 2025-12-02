from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.coda.connector import CodaColumn
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.coda.connector import CodaDoc
from onyx.connectors.coda.connector import CodaRow
from onyx.connectors.coda.connector import CodaTable
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource


@pytest.fixture
def connector():
    return CodaConnector()


@pytest.fixture
def mock_doc():
    return CodaDoc(
        id="doc-123",
        type="doc",
        href="https://coda.io/d/123",
        browserLink="https://coda.io/d/123",
        name="Test Doc",
        owner="user-1",
        ownerName="Test User",
        createdAt="2023-01-01T00:00:00Z",
        updatedAt="2023-01-02T00:00:00Z",
    )


@pytest.fixture
def mock_table():
    return CodaTable(
        id="table-1",
        type="table",
        href="https://coda.io/d/123/table-1",
        browserLink="https://coda.io/d/123/table-1",
        name="Test Table",
        parent={"id": "doc-123", "type": "doc"},
        rowCount=10,
        sorts=[],
        layout="default",
        createdAt="2023-01-01T00:00:00Z",
        updatedAt="2023-01-02T00:00:00Z",
    )


@pytest.fixture
def mock_columns():
    return [
        CodaColumn(
            id="col-1",
            type="text",
            href="link",
            name="Name",
            display=True,
            calculated=False,
        ),
        CodaColumn(
            id="col-2",
            type="number",
            href="link",
            name="Age",
            display=True,
            calculated=False,
        ),
        CodaColumn(
            id="col-3",
            type="text",
            href="link",
            name="Hidden",
            display=False,
            calculated=False,
        ),
    ]


@pytest.fixture
def mock_rows():
    return [
        CodaRow(
            id="row-1",
            type="row",
            href="link",
            name="Row 1",
            index=0,
            createdAt="2023-01-01T00:00:00Z",
            updatedAt="2023-01-01T00:00:00Z",
            browserLink="link",
            values={"col-1": "Alice", "col-2": 30, "col-3": "Secret"},
        ),
        CodaRow(
            id="row-2",
            type="row",
            href="link",
            name="Row 2",
            index=1,
            createdAt="2023-01-01T00:00:00Z",
            updatedAt="2023-01-01T00:00:00Z",
            browserLink="link",
            values={"col-1": "Bob", "col-2": 25, "col-3": "Secret"},
        ),
    ]


def test_convert_table_to_markdown(connector, mock_table, mock_columns, mock_rows):
    markdown = connector._convert_table_to_markdown(mock_table, mock_columns, mock_rows)

    expected_lines = [
        "# Test Table",
        "| Name | Age |",
        "| --- | --- |",
        "| Alice | 30 |",
        "| Bob | 25 |",
    ]

    # Check that all expected lines are present (ignoring whitespace differences)
    actual_lines = [line.strip() for line in markdown.split("\n") if line.strip()]
    for expected in expected_lines:
        assert expected in actual_lines


def test_convert_table_to_markdown_empty_rows(connector, mock_table, mock_columns):
    markdown = connector._convert_table_to_markdown(mock_table, mock_columns, [])
    assert "*Empty table - no data*" in markdown


def test_convert_table_to_markdown_no_columns(connector, mock_table, mock_rows):
    markdown = connector._convert_table_to_markdown(mock_table, [], mock_rows)
    assert "*Empty table - no columns defined*" in markdown


def test_format_cell_value(connector):
    # Test simple types
    assert connector._format_cell_value("text") == "text"
    assert connector._format_cell_value(123) == "123"
    assert connector._format_cell_value(True) == "✓"
    assert connector._format_cell_value(False) == ""
    assert connector._format_cell_value(None) == ""

    # Test escaping
    assert connector._format_cell_value("a|b") == "a\\|b"
    assert connector._format_cell_value("a\nb") == "a b"

    # Test complex types
    assert connector._format_cell_value(["a", "b"]) == "a, b"
    assert connector._format_cell_value({"name": "Person"}) == "Person"
    assert (
        connector._format_cell_value({"url": "http://example.com"})
        == "http://example.com"
    )


@patch("onyx.connectors.coda.connector.rl_requests.get")
def test_fetch_tables(mock_get, connector):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [{"id": "table-1", "name": "Test Table"}]
    }
    mock_get.return_value = mock_response

    result = connector._fetch_tables("doc-123")

    assert result["items"][0]["id"] == "table-1"
    mock_get.assert_called_with(
        "https://coda.io/apis/v1/docs/doc-123/tables",
        headers=connector.headers,
        params={"limit": 100},
        timeout=30,
    )


@patch("onyx.connectors.coda.connector.rl_requests.get")
def test_fetch_table_rows_pagination(mock_get, connector):
    mock_response = MagicMock()
    mock_response.json.return_value = {"items": [], "nextPageToken": "token"}
    mock_get.return_value = mock_response

    connector._fetch_table_rows("doc-123", "table-1", page_token="prev-token", limit=50)

    mock_get.assert_called_with(
        "https://coda.io/apis/v1/docs/doc-123/tables/table-1/rows",
        headers=connector.headers,
        params={"limit": 50, "useColumnNames": False, "pageToken": "prev-token"},
        timeout=30,
    )


def test_read_tables_generates_documents(
    connector, mock_doc, mock_table, mock_columns, mock_rows
):
    # Mock API calls
    connector._fetch_table_columns = MagicMock(
        return_value={"items": [col.model_dump() for col in mock_columns]}
    )
    connector._fetch_table_rows = MagicMock(
        return_value={"items": [row.model_dump() for row in mock_rows]}
    )

    # Run generator
    gen = connector._read_tables(mock_doc, [mock_table])
    docs = list(gen)

    assert len(docs) == 1
    doc = docs[0]

    assert isinstance(doc, Document)
    assert doc.id == "doc-123:table:table-1"
    assert doc.semantic_identifier == "Test Doc - Test Table"
    assert doc.source == DocumentSource.CODA
    assert "row_count" in doc.metadata
    assert doc.metadata["row_count"] == "2"
    assert doc.metadata["column_count"] == "3"

    # Check content
    assert "| Name | Age |" in doc.sections[0].text
    assert "| Alice | 30 |" in doc.sections[0].text


def test_read_tables_row_limit(connector, mock_doc, mock_table, mock_columns):
    # Setup connector with small limit
    connector.max_table_rows = 5

    # Mock API to return more rows than limit
    many_rows = []
    for i in range(10):
        row = CodaRow(
            id=f"row-{i}",
            type="row",
            href="",
            name=f"Row {i}",
            index=i,
            createdAt="",
            updatedAt="",
            browserLink="",
            values={"col-1": f"Val {i}"},
        )
        many_rows.append(row.model_dump())

    connector._fetch_table_columns = MagicMock(
        return_value={"items": [col.model_dump() for col in mock_columns]}
    )

    # Mock pagination
    def side_effect(*args, **kwargs):
        limit = kwargs.get("limit", 100)
        start = 0 if not args[2] else 5  # simplistic mock logic
        items = many_rows[start : start + limit]
        next_token = "token" if start + limit < 10 else None
        return {"items": items, "nextPageToken": next_token}

    connector._fetch_table_rows = MagicMock(side_effect=side_effect)

    # Run generator
    gen = connector._read_tables(mock_doc, [mock_table])
    docs = list(gen)

    assert len(docs) == 1
    doc = docs[0]

    # Should only have fetched up to max_table_rows (5)
    # The mock side effect is a bit simple, but the key is verifying the connector logic
    # In the connector logic:
    # 1. rows_fetched = 0, limit = 5. Call fetch. Get 5 rows. rows_fetched = 5.
    # 2. Loop condition rows_fetched < 5 is False. Break.

    assert doc.metadata["row_count"] == "5"
    assert "*Showing 5 of 10 rows*" in doc.sections[0].text
