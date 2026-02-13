from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.airtable.airtable_connector import AirtableConnector
from onyx.connectors.airtable.airtable_connector import parse_airtable_url
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import Document


def _make_field_schema(field_id: str, name: str, field_type: str) -> MagicMock:
    field = MagicMock()
    field.id = field_id
    field.name = name
    field.type = field_type
    return field


def _make_table_schema(
    table_id: str,
    table_name: str,
    primary_field_id: str,
    fields: list[MagicMock],
) -> MagicMock:
    schema = MagicMock()
    schema.id = table_id
    schema.name = table_name
    schema.primary_field_id = primary_field_id
    schema.fields = fields
    schema.views = []
    return schema


def _make_record(record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"id": record_id, "fields": fields}


def _make_base_info(base_id: str, name: str) -> MagicMock:
    info = MagicMock()
    info.id = base_id
    info.name = name
    return info


def _make_table_obj(table_id: str, name: str) -> MagicMock:
    obj = MagicMock()
    obj.id = table_id
    obj.name = name
    return obj


def _setup_mock_api(
    bases: list[dict[str, Any]],
) -> MagicMock:
    """Set up a mock AirtableApi with bases, tables, records, and schemas.

    Args:
        bases: List of dicts with keys: id, name, tables.
               Each table is a dict with: id, name, primary_field_id, fields, records.
               Each field is a dict with: id, name, type.
               Each record is a dict with: id, fields.
    """
    mock_api = MagicMock()

    base_infos = [_make_base_info(b["id"], b["name"]) for b in bases]
    mock_api.bases.return_value = base_infos

    def base_side_effect(base_id: str) -> MagicMock:
        mock_base = MagicMock()
        base_data = next((b for b in bases if b["id"] == base_id), None)
        if not base_data:
            raise ValueError(f"Unknown base: {base_id}")

        table_objs = [_make_table_obj(t["id"], t["name"]) for t in base_data["tables"]]
        mock_base.tables.return_value = table_objs
        return mock_base

    mock_api.base.side_effect = base_side_effect

    def table_side_effect(base_id: str, table_name_or_id: str) -> MagicMock:
        base_data = next((b for b in bases if b["id"] == base_id), None)
        if not base_data:
            raise ValueError(f"Unknown base: {base_id}")

        table_data = next(
            (
                t
                for t in base_data["tables"]
                if t["id"] == table_name_or_id or t["name"] == table_name_or_id
            ),
            None,
        )
        if not table_data:
            raise ValueError(f"Unknown table: {table_name_or_id}")

        mock_table = MagicMock()
        mock_table.name = table_data["name"]
        mock_table.all.return_value = [
            _make_record(r["id"], r["fields"]) for r in table_data["records"]
        ]

        field_schemas = [
            _make_field_schema(f["id"], f["name"], f["type"])
            for f in table_data["fields"]
        ]
        schema = _make_table_schema(
            table_data["id"],
            table_data["name"],
            table_data["primary_field_id"],
            field_schemas,
        )
        mock_table.schema.return_value = schema
        return mock_table

    mock_api.table.side_effect = table_side_effect
    return mock_api


SAMPLE_BASES = [
    {
        "id": "appBASE1",
        "name": "Base One",
        "tables": [
            {
                "id": "tblTABLE1",
                "name": "Table A",
                "primary_field_id": "fld1",
                "fields": [
                    {"id": "fld1", "name": "Name", "type": "singleLineText"},
                    {"id": "fld2", "name": "Notes", "type": "multilineText"},
                ],
                "records": [
                    {"id": "recA1", "fields": {"Name": "Alice", "Notes": "Note A"}},
                    {"id": "recA2", "fields": {"Name": "Bob", "Notes": "Note B"}},
                ],
            },
            {
                "id": "tblTABLE2",
                "name": "Table B",
                "primary_field_id": "fld3",
                "fields": [
                    {"id": "fld3", "name": "Title", "type": "singleLineText"},
                    {"id": "fld4", "name": "Status", "type": "singleSelect"},
                ],
                "records": [
                    {"id": "recB1", "fields": {"Title": "Task 1", "Status": "Done"}},
                ],
            },
        ],
    },
    {
        "id": "appBASE2",
        "name": "Base Two",
        "tables": [
            {
                "id": "tblTABLE3",
                "name": "Table C",
                "primary_field_id": "fld5",
                "fields": [
                    {"id": "fld5", "name": "Item", "type": "singleLineText"},
                ],
                "records": [
                    {"id": "recC1", "fields": {"Item": "Widget"}},
                ],
            },
        ],
    },
]


def _collect_docs(connector: AirtableConnector) -> list[Document]:
    docs: list[Document] = []
    for batch in connector.load_from_state():
        for item in batch:
            if isinstance(item, Document):
                docs.append(item)
    return docs


class TestIndexAll:
    @patch("time.sleep")
    def test_index_all_discovers_all_bases_and_tables(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        connector = AirtableConnector()
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        # 2 records from Table A + 1 from Table B + 1 from Table C = 4
        assert len(docs) == 4
        doc_ids = {d.id for d in docs}
        assert doc_ids == {
            "airtable__recA1",
            "airtable__recA2",
            "airtable__recB1",
            "airtable__recC1",
        }

    @patch("time.sleep")
    def test_index_all_semantic_id_includes_base_name(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        connector = AirtableConnector()
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)
        docs_by_id = {d.id: d for d in docs}

        assert (
            docs_by_id["airtable__recA1"].semantic_identifier
            == "Base One > Table A: Alice"
        )
        assert (
            docs_by_id["airtable__recB1"].semantic_identifier
            == "Base One > Table B: Task 1"
        )
        assert (
            docs_by_id["airtable__recC1"].semantic_identifier
            == "Base Two > Table C: Widget"
        )

    @patch("time.sleep")
    def test_index_all_hierarchy_source_path(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        """Verify doc_metadata hierarchy source_path is [base_name, table_name]."""
        connector = AirtableConnector()
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)
        docs_by_id = {d.id: d for d in docs}

        doc_a1 = docs_by_id["airtable__recA1"]
        assert doc_a1.doc_metadata is not None
        assert doc_a1.doc_metadata["hierarchy"]["source_path"] == [
            "Base One",
            "Table A",
        ]
        assert doc_a1.doc_metadata["hierarchy"]["base_name"] == "Base One"
        assert doc_a1.doc_metadata["hierarchy"]["table_name"] == "Table A"

        doc_c1 = docs_by_id["airtable__recC1"]
        assert doc_c1.doc_metadata is not None
        assert doc_c1.doc_metadata["hierarchy"]["source_path"] == [
            "Base Two",
            "Table C",
        ]

    @patch("time.sleep")
    def test_index_all_empty_account(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        connector = AirtableConnector()
        mock_api = MagicMock()
        mock_api.bases.return_value = []
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)
        assert len(docs) == 0

    @patch("time.sleep")
    def test_index_all_skips_failing_table(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        """If one table fails, other tables should still be indexed."""
        bases = [
            {
                "id": "appBASE1",
                "name": "Base One",
                "tables": [
                    {
                        "id": "tblGOOD",
                        "name": "Good Table",
                        "primary_field_id": "fld1",
                        "fields": [
                            {"id": "fld1", "name": "Name", "type": "singleLineText"},
                        ],
                        "records": [
                            {"id": "recOK", "fields": {"Name": "Works"}},
                        ],
                    },
                    {
                        "id": "tblBAD",
                        "name": "Bad Table",
                        "primary_field_id": "fldX",
                        "fields": [],
                        "records": [],
                    },
                ],
            },
        ]
        mock_api = _setup_mock_api(bases)

        # Make the bad table raise an error when fetching records
        original_table_side_effect = mock_api.table.side_effect

        def table_with_failure(base_id: str, table_name_or_id: str) -> MagicMock:
            if table_name_or_id == "tblBAD":
                mock_table = MagicMock()
                mock_table.all.side_effect = Exception("API Error")
                mock_table.schema.side_effect = Exception("API Error")
                return mock_table
            return original_table_side_effect(base_id, table_name_or_id)

        mock_api.table.side_effect = table_with_failure
        connector = AirtableConnector()
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        # Only the good table's records should come through
        assert len(docs) == 1
        assert docs[0].id == "airtable__recOK"

    @patch("time.sleep")
    def test_index_all_skips_failing_base(
        self, mock_sleep: MagicMock  # noqa: ARG002
    ) -> None:
        """If listing tables for a base fails, other bases should still be indexed."""
        bases_data = [
            {
                "id": "appGOOD",
                "name": "Good Base",
                "tables": [
                    {
                        "id": "tblOK",
                        "name": "OK Table",
                        "primary_field_id": "fld1",
                        "fields": [
                            {"id": "fld1", "name": "Name", "type": "singleLineText"},
                        ],
                        "records": [
                            {"id": "recOK", "fields": {"Name": "Works"}},
                        ],
                    },
                ],
            },
        ]
        mock_api = _setup_mock_api(bases_data)

        # Add a bad base that fails on tables()
        bad_base_info = _make_base_info("appBAD", "Bad Base")
        mock_api.bases.return_value = [
            bad_base_info,
            *mock_api.bases.return_value,
        ]

        original_base_side_effect = mock_api.base.side_effect

        def base_with_failure(base_id: str) -> MagicMock:
            if base_id == "appBAD":
                mock_base = MagicMock()
                mock_base.tables.side_effect = Exception("Permission denied")
                return mock_base
            return original_base_side_effect(base_id)

        mock_api.base.side_effect = base_with_failure

        connector = AirtableConnector()
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        assert len(docs) == 1
        assert docs[0].id == "airtable__recOK"


class TestSpecificTableMode:
    def test_specific_table_unchanged(self) -> None:
        """Verify the original single-table behavior still works."""
        bases = [
            {
                "id": "appBASE1",
                "name": "Base One",
                "tables": [
                    {
                        "id": "tblTABLE1",
                        "name": "Table A",
                        "primary_field_id": "fld1",
                        "fields": [
                            {"id": "fld1", "name": "Name", "type": "singleLineText"},
                            {"id": "fld2", "name": "Notes", "type": "multilineText"},
                        ],
                        "records": [
                            {
                                "id": "recA1",
                                "fields": {"Name": "Alice", "Notes": "Note"},
                            },
                        ],
                    },
                ],
            },
        ]
        mock_api = _setup_mock_api(bases)

        connector = AirtableConnector(
            base_id="appBASE1",
            table_name_or_id="tblTABLE1",
        )
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        assert len(docs) == 1
        assert docs[0].id == "airtable__recA1"
        # No base name prefix in specific mode
        assert docs[0].semantic_identifier == "Table A: Alice"

    def test_specific_table_resolves_base_name_for_hierarchy(self) -> None:
        """In specific mode, bases() is called to resolve the base name for hierarchy."""
        bases = [
            {
                "id": "appBASE1",
                "name": "Base One",
                "tables": [
                    {
                        "id": "tblTABLE1",
                        "name": "Table A",
                        "primary_field_id": "fld1",
                        "fields": [
                            {"id": "fld1", "name": "Name", "type": "singleLineText"},
                        ],
                        "records": [
                            {"id": "recA1", "fields": {"Name": "Test"}},
                        ],
                    },
                ],
            },
        ]
        mock_api = _setup_mock_api(bases)

        connector = AirtableConnector(
            base_id="appBASE1",
            table_name_or_id="tblTABLE1",
        )
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        # bases() is called to resolve the base name for hierarchy source_path
        mock_api.bases.assert_called_once()
        # But base().tables() should NOT be called (no discovery)
        mock_api.base.assert_not_called()
        # Semantic identifier should NOT include base name in specific mode
        assert docs[0].semantic_identifier == "Table A: Test"
        # Hierarchy should include base name for Craft file system
        assert docs[0].doc_metadata is not None
        assert docs[0].doc_metadata["hierarchy"]["source_path"] == [
            "Base One",
            "Table A",
        ]


class TestValidateConnectorSettings:
    def test_validate_index_all_success(self) -> None:
        connector = AirtableConnector()
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api

        # Should not raise
        connector.validate_connector_settings()

    def test_validate_index_all_no_bases(self) -> None:
        connector = AirtableConnector()
        mock_api = MagicMock()
        mock_api.bases.return_value = []
        connector._airtable_client = mock_api

        with pytest.raises(ConnectorValidationError, match="No bases found"):
            connector.validate_connector_settings()

    def test_validate_specific_table_success(self) -> None:
        connector = AirtableConnector(
            base_id="appBASE1",
            table_name_or_id="tblTABLE1",
        )
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api

        # Should not raise
        connector.validate_connector_settings()

    def test_validate_empty_fields_auto_detects_index_all(self) -> None:
        """Empty base_id + table_name_or_id auto-detects as index_all mode."""
        connector = AirtableConnector(
            base_id="",
            table_name_or_id="",
        )
        assert connector.index_all is True

        # Validation should go through the index_all path
        mock_api = _setup_mock_api(SAMPLE_BASES)
        connector._airtable_client = mock_api
        connector.validate_connector_settings()

    def test_validate_specific_table_api_error(self) -> None:
        connector = AirtableConnector(
            base_id="appBAD",
            table_name_or_id="tblBAD",
        )
        mock_api = MagicMock()
        mock_table = MagicMock()
        mock_table.schema.side_effect = Exception("Not found")
        mock_api.table.return_value = mock_table
        connector._airtable_client = mock_api

        with pytest.raises(ConnectorValidationError, match="Failed to access table"):
            connector.validate_connector_settings()


class TestParseAirtableUrl:
    def test_full_url_with_view(self) -> None:
        base_id, table_id, view_id = parse_airtable_url(
            "https://airtable.com/appZqBgQFQ6kWyeZK/tblc9prNLypy7olTV/viwa3yxZvqWnyXftm?blocks=hide"
        )
        assert base_id == "appZqBgQFQ6kWyeZK"
        assert table_id == "tblc9prNLypy7olTV"
        assert view_id == "viwa3yxZvqWnyXftm"

    def test_url_without_view(self) -> None:
        base_id, table_id, view_id = parse_airtable_url(
            "https://airtable.com/appZqBgQFQ6kWyeZK/tblc9prNLypy7olTV"
        )
        assert base_id == "appZqBgQFQ6kWyeZK"
        assert table_id == "tblc9prNLypy7olTV"
        assert view_id is None

    def test_url_without_query_params(self) -> None:
        base_id, table_id, view_id = parse_airtable_url(
            "https://airtable.com/appABC123/tblDEF456/viwGHI789"
        )
        assert base_id == "appABC123"
        assert table_id == "tblDEF456"
        assert view_id == "viwGHI789"

    def test_url_with_trailing_whitespace(self) -> None:
        base_id, table_id, view_id = parse_airtable_url(
            "  https://airtable.com/appABC123/tblDEF456  "
        )
        assert base_id == "appABC123"
        assert table_id == "tblDEF456"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_airtable_url("https://google.com/something")

    def test_missing_table_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_airtable_url("https://airtable.com/appABC123")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_airtable_url("")


class TestAirtableUrlConnector:
    def test_url_sets_base_and_table_ids(self) -> None:
        connector = AirtableConnector(
            airtable_url="https://airtable.com/appZqBgQFQ6kWyeZK/tblc9prNLypy7olTV/viwa3yxZvqWnyXftm?blocks=hide"
        )
        assert connector.base_id == "appZqBgQFQ6kWyeZK"
        assert connector.table_name_or_id == "tblc9prNLypy7olTV"
        assert connector.view_id == "viwa3yxZvqWnyXftm"

    def test_url_without_view_leaves_view_none(self) -> None:
        connector = AirtableConnector(airtable_url="https://airtable.com/appABC/tblDEF")
        assert connector.base_id == "appABC"
        assert connector.table_name_or_id == "tblDEF"
        assert connector.view_id is None

    def test_url_overrides_explicit_base_and_table(self) -> None:
        connector = AirtableConnector(
            base_id="appOLD",
            table_name_or_id="tblOLD",
            airtable_url="https://airtable.com/appNEW/tblNEW",
        )
        assert connector.base_id == "appNEW"
        assert connector.table_name_or_id == "tblNEW"

    def test_url_indexes_correctly(self) -> None:
        """End-to-end: URL-configured connector fetches from the right table."""
        bases = [
            {
                "id": "appFromUrl",
                "name": "URL Base",
                "tables": [
                    {
                        "id": "tblFromUrl",
                        "name": "URL Table",
                        "primary_field_id": "fld1",
                        "fields": [
                            {"id": "fld1", "name": "Name", "type": "singleLineText"},
                        ],
                        "records": [
                            {"id": "recURL1", "fields": {"Name": "From URL"}},
                        ],
                    },
                ],
            },
        ]
        mock_api = _setup_mock_api(bases)

        connector = AirtableConnector(
            airtable_url="https://airtable.com/appFromUrl/tblFromUrl/viwABC"
        )
        connector._airtable_client = mock_api

        docs = _collect_docs(connector)

        assert len(docs) == 1
        assert docs[0].id == "airtable__recURL1"
        assert docs[0].semantic_identifier == "URL Table: From URL"
