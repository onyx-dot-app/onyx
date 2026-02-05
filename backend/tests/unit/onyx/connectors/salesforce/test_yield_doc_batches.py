"""Unit tests for _yield_doc_batches and metadata type conversion in SalesforceConnector."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.salesforce.connector import _convert_to_metadata_value
from onyx.connectors.salesforce.connector import SalesforceConnector
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.connectors.salesforce.utils import MODIFIED_FIELD
from onyx.connectors.salesforce.utils import NAME_FIELD
from onyx.connectors.salesforce.utils import SalesforceObject


class TestConvertToMetadataValue:
    """Tests for the _convert_to_metadata_value helper function."""

    def test_string_value(self) -> None:
        """String values should be returned as-is."""
        assert _convert_to_metadata_value("hello") == "hello"
        assert _convert_to_metadata_value("") == ""

    def test_boolean_true(self) -> None:
        """Boolean True should be converted to string 'True'."""
        assert _convert_to_metadata_value(True) == "True"

    def test_boolean_false(self) -> None:
        """Boolean False should be converted to string 'False'."""
        assert _convert_to_metadata_value(False) == "False"

    def test_integer_value(self) -> None:
        """Integer values should be converted to string."""
        assert _convert_to_metadata_value(42) == "42"
        assert _convert_to_metadata_value(0) == "0"
        assert _convert_to_metadata_value(-100) == "-100"

    def test_float_value(self) -> None:
        """Float values should be converted to string."""
        assert _convert_to_metadata_value(3.14) == "3.14"
        assert _convert_to_metadata_value(0.0) == "0.0"
        assert _convert_to_metadata_value(-2.5) == "-2.5"

    def test_list_of_strings(self) -> None:
        """List of strings should remain as list of strings."""
        result = _convert_to_metadata_value(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_list_of_mixed_types(self) -> None:
        """List with mixed types should have all items converted to strings."""
        result = _convert_to_metadata_value([1, True, 3.14, "text"])
        assert result == ["1", "True", "3.14", "text"]

    def test_empty_list(self) -> None:
        """Empty list should return empty list."""
        assert _convert_to_metadata_value([]) == []


class TestYieldDocBatches:
    """Tests for the _yield_doc_batches method of SalesforceConnector."""

    @pytest.fixture
    def connector(self) -> SalesforceConnector:
        """Create a SalesforceConnector instance with mocked sf_client."""
        connector = SalesforceConnector(
            batch_size=10,
            requested_objects=["Opportunity"],
        )
        # Mock the sf_client property
        mock_sf_client = MagicMock()
        mock_sf_client.sf_instance = "test.salesforce.com"
        connector._sf_client = mock_sf_client
        return connector

    @pytest.fixture
    def mock_sf_db(self) -> MagicMock:
        """Create a mock OnyxSalesforceSQLite object."""
        return MagicMock()

    def _create_salesforce_object(
        self,
        object_id: str,
        object_type: str,
        data: dict[str, Any],
    ) -> SalesforceObject:
        """Helper to create a SalesforceObject with required fields."""
        # Ensure required fields are present
        data.setdefault(ID_FIELD, object_id)
        data.setdefault(MODIFIED_FIELD, "2024-01-15T10:30:00.000Z")
        data.setdefault(NAME_FIELD, f"Test {object_type}")
        return SalesforceObject(id=object_id, type=object_type, data=data)

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_metadata_type_conversion_for_opportunity(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test that Opportunity metadata fields are properly type-converted."""
        parent_id = "006bm000006kyDpAAI"
        parent_type = "Opportunity"

        # Create a parent object with various data types in the fields
        parent_data = {
            ID_FIELD: parent_id,
            NAME_FIELD: "Test Opportunity",
            MODIFIED_FIELD: "2024-01-15T10:30:00.000Z",
            "Account": "Acme Corp",  # string - should become "account" metadata
            "FiscalQuarter": 2,  # int - should be converted to "2"
            "FiscalYear": 2024,  # int - should be converted to "2024"
            "IsClosed": False,  # bool - should be converted to "False"
            "StageName": "Prospecting",  # string
            "Type": "New Business",  # string
            "Amount": 50000.50,  # float - should be converted to "50000.50"
            "CloseDate": "2024-06-30",  # string
            "Probability": 75,  # int - should be converted to "75"
            "CreatedDate": "2024-01-01T00:00:00.000Z",  # string
        }
        parent_object = self._create_salesforce_object(
            parent_id, parent_type, parent_data
        )

        # Setup mock sf_db
        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, parent_id, 1)]
        )
        mock_sf_db.get_record.return_value = parent_object
        mock_sf_db.file_size = 1024

        # Create a mock document that convert_sf_object_to_doc will return
        mock_doc = Document(
            id=f"SALESFORCE_{parent_id}",
            sections=[],
            source=DocumentSource.SALESFORCE,
            semantic_identifier="Test Opportunity",
            metadata={},
        )
        mock_convert.return_value = mock_doc

        # Track parent changes
        parents_changed = 0

        def increment() -> None:
            nonlocal parents_changed
            parents_changed += 1

        # Call _yield_doc_batches
        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {parent_id: parent_type}
        parent_types = {parent_type}

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                increment,
            )
        )

        # Verify we got one batch with one document
        assert len(batches) == 1
        docs = batches[0]
        assert len(docs) == 1

        doc = docs[0]
        assert isinstance(doc, Document)

        # Verify metadata type conversions
        # All values should be strings (or list of strings)
        assert doc.metadata["object_type"] == "Opportunity"
        assert doc.metadata["account"] == "Acme Corp"  # string stays string
        assert doc.metadata["fiscal_quarter"] == "2"  # int -> str
        assert doc.metadata["fiscal_year"] == "2024"  # int -> str
        assert doc.metadata["is_closed"] == "False"  # bool -> str
        assert doc.metadata["stage_name"] == "Prospecting"  # string stays string
        assert doc.metadata["type"] == "New Business"  # string stays string
        assert (
            doc.metadata["amount"] == "50000.5"
        )  # float -> str (Python drops trailing zeros)
        assert doc.metadata["close_date"] == "2024-06-30"  # string stays string
        assert doc.metadata["probability"] == "75"  # int -> str
        assert doc.metadata["name"] == "Test Opportunity"  # NAME_FIELD

        # Verify parent was counted
        assert parents_changed == 1
        assert type_to_processed[parent_type] == 1

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_missing_optional_metadata_fields(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test that missing optional metadata fields are not added."""
        parent_id = "006bm000006kyDqAAI"
        parent_type = "Opportunity"

        # Create parent object with only some fields
        parent_data = {
            ID_FIELD: parent_id,
            NAME_FIELD: "Minimal Opportunity",
            MODIFIED_FIELD: "2024-01-15T10:30:00.000Z",
            "StageName": "Closed Won",
            # Notably missing: Amount, Probability, FiscalQuarter, etc.
        }
        parent_object = self._create_salesforce_object(
            parent_id, parent_type, parent_data
        )

        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, parent_id, 1)]
        )
        mock_sf_db.get_record.return_value = parent_object
        mock_sf_db.file_size = 1024

        mock_doc = Document(
            id=f"SALESFORCE_{parent_id}",
            sections=[],
            source=DocumentSource.SALESFORCE,
            semantic_identifier="Minimal Opportunity",
            metadata={},
        )
        mock_convert.return_value = mock_doc

        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {parent_id: parent_type}
        parent_types = {parent_type}

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                lambda: None,
            )
        )

        doc = batches[0][0]
        assert isinstance(doc, Document)

        # Only present fields should be in metadata
        assert "stage_name" in doc.metadata
        assert doc.metadata["stage_name"] == "Closed Won"
        assert "name" in doc.metadata
        assert doc.metadata["name"] == "Minimal Opportunity"

        # Missing fields should not be in metadata
        assert "amount" not in doc.metadata
        assert "probability" not in doc.metadata
        assert "fiscal_quarter" not in doc.metadata
        assert "fiscal_year" not in doc.metadata
        assert "is_closed" not in doc.metadata

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_contact_metadata_fields(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test metadata conversion for Contact object type."""
        parent_id = "003bm00000EjHCjAAN"
        parent_type = "Contact"

        parent_data = {
            ID_FIELD: parent_id,
            NAME_FIELD: "John Doe",
            MODIFIED_FIELD: "2024-02-20T14:00:00.000Z",
            "Account": "Globex Corp",
            "CreatedDate": "2024-01-01T00:00:00.000Z",
        }
        parent_object = self._create_salesforce_object(
            parent_id, parent_type, parent_data
        )

        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, parent_id, 1)]
        )
        mock_sf_db.get_record.return_value = parent_object
        mock_sf_db.file_size = 1024

        mock_doc = Document(
            id=f"SALESFORCE_{parent_id}",
            sections=[],
            source=DocumentSource.SALESFORCE,
            semantic_identifier="John Doe",
            metadata={},
        )
        mock_convert.return_value = mock_doc

        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {parent_id: parent_type}
        parent_types = {parent_type}

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                lambda: None,
            )
        )

        doc = batches[0][0]
        assert isinstance(doc, Document)

        # Verify Contact-specific metadata
        assert doc.metadata["object_type"] == "Contact"
        assert doc.metadata["account"] == "Globex Corp"
        assert doc.metadata["created_date"] == "2024-01-01T00:00:00.000Z"
        assert doc.metadata["last_modified_date"] == "2024-02-20T14:00:00.000Z"

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_no_default_attributes_for_unknown_type(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test that unknown object types only get object_type metadata."""
        parent_id = "001bm00000fd9Z3AAI"
        parent_type = "CustomObject__c"

        parent_data = {
            ID_FIELD: parent_id,
            NAME_FIELD: "Custom Record",
            MODIFIED_FIELD: "2024-03-01T08:00:00.000Z",
            "CustomField__c": "custom value",
            "NumberField__c": 123,
        }
        parent_object = self._create_salesforce_object(
            parent_id, parent_type, parent_data
        )

        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, parent_id, 1)]
        )
        mock_sf_db.get_record.return_value = parent_object
        mock_sf_db.file_size = 1024

        mock_doc = Document(
            id=f"SALESFORCE_{parent_id}",
            sections=[],
            source=DocumentSource.SALESFORCE,
            semantic_identifier="Custom Record",
            metadata={},
        )
        mock_convert.return_value = mock_doc

        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {parent_id: parent_type}
        parent_types = {parent_type}

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                lambda: None,
            )
        )

        doc = batches[0][0]
        assert isinstance(doc, Document)

        # Only object_type should be set for unknown types
        assert doc.metadata["object_type"] == "CustomObject__c"
        # Custom fields should NOT be in metadata (not in _DEFAULT_ATTRIBUTES_TO_KEEP)
        assert "CustomField__c" not in doc.metadata
        assert "NumberField__c" not in doc.metadata

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_skips_missing_parent_objects(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test that missing parent objects are skipped gracefully."""
        parent_id = "006bm000006kyDrAAI"
        parent_type = "Opportunity"

        # get_record returns None for missing object
        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, parent_id, 1)]
        )
        mock_sf_db.get_record.return_value = None
        mock_sf_db.file_size = 1024

        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {parent_id: parent_type}
        parent_types = {parent_type}

        parents_changed = 0

        def increment() -> None:
            nonlocal parents_changed
            parents_changed += 1

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                increment,
            )
        )

        # Should yield one empty batch
        assert len(batches) == 1
        assert len(batches[0]) == 0

        # convert_sf_object_to_doc should not have been called
        mock_convert.assert_not_called()

        # Parents changed should still be 0
        assert parents_changed == 0

    @patch("onyx.connectors.salesforce.connector.convert_sf_object_to_doc")
    def test_multiple_documents_batching(
        self,
        mock_convert: MagicMock,
        connector: SalesforceConnector,
        mock_sf_db: MagicMock,
    ) -> None:
        """Test that multiple documents are correctly batched."""
        # Create 3 parent objects
        parent_ids = [
            "006bm000006kyDsAAI",
            "006bm000006kyDtAAI",
            "006bm000006kyDuAAI",
        ]
        parent_type = "Opportunity"

        parent_objects = [
            self._create_salesforce_object(
                pid,
                parent_type,
                {
                    ID_FIELD: pid,
                    NAME_FIELD: f"Opportunity {i}",
                    MODIFIED_FIELD: "2024-01-15T10:30:00.000Z",
                    "IsClosed": i % 2 == 0,  # alternating bool values
                    "Amount": 1000.0 * (i + 1),
                },
            )
            for i, pid in enumerate(parent_ids)
        ]

        # Setup mock to return all three
        mock_sf_db.get_changed_parent_ids_by_type.return_value = iter(
            [(parent_type, pid, i + 1) for i, pid in enumerate(parent_ids)]
        )
        mock_sf_db.get_record.side_effect = parent_objects
        mock_sf_db.file_size = 1024

        # Create mock documents
        mock_docs = [
            Document(
                id=f"SALESFORCE_{pid}",
                sections=[],
                source=DocumentSource.SALESFORCE,
                semantic_identifier=f"Opportunity {i}",
                metadata={},
            )
            for i, pid in enumerate(parent_ids)
        ]
        mock_convert.side_effect = mock_docs

        type_to_processed: dict[str, int] = {}
        changed_ids_to_type = {pid: parent_type for pid in parent_ids}
        parent_types = {parent_type}

        batches = list(
            connector._yield_doc_batches(
                mock_sf_db,
                type_to_processed,
                changed_ids_to_type,
                parent_types,
                lambda: None,
            )
        )

        # With batch_size=10, all 3 docs should be in one batch
        assert len(batches) == 1
        assert len(batches[0]) == 3

        # Verify each document has correct metadata
        for i, doc in enumerate(batches[0]):
            assert isinstance(doc, Document)
            assert doc.metadata["object_type"] == "Opportunity"
            assert doc.metadata["is_closed"] == str(i % 2 == 0)
            assert doc.metadata["amount"] == str(1000.0 * (i + 1))

        assert type_to_processed[parent_type] == 3
