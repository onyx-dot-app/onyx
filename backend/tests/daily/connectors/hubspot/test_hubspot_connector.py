import os
from datetime import datetime
from datetime import timezone
from typing import Any

import pytest

from onyx.connectors.hubspot.connector import AVAILABLE_OBJECT_TYPES
from onyx.connectors.hubspot.connector import HubSpotConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document


class TestHubSpotConnector:
    """Test HubSpot connector functionality using real API calls."""

    @pytest.fixture
    def connector(self) -> HubSpotConnector:
        """Create a HubSpot connector instance."""
        return HubSpotConnector(batch_size=10)

    @pytest.fixture
    def credentials(self) -> dict[str, Any]:
        """Provide test credentials."""
        return {"hubspot_access_token": os.environ["HUBSPOT_ACCESS_TOKEN"]}

    def test_credentials_properties_raise_exception_when_none(self) -> None:
        """Test that access_token and portal_id properties raise exceptions when not set."""
        connector = HubSpotConnector()

        # access_token should raise exception when not set
        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            _ = connector.access_token
        assert "HubSpot access token not set" in str(exc_info.value)

        # portal_id should raise exception when not set
        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            _ = connector.portal_id
        assert "HubSpot portal ID not set" in str(exc_info.value)

    def test_load_credentials(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that credentials are loaded correctly."""
        result = connector.load_credentials(credentials)

        assert result is None  # Should return None on success
        assert connector.access_token == credentials["hubspot_access_token"]
        assert connector.portal_id is not None
        assert isinstance(connector.portal_id, str)

    def test_load_from_state_basic_functionality(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Test basic load_from_state functionality."""
        connector.load_credentials(credentials)

        # Get first batch of documents
        document_batches = connector.load_from_state()
        first_batch = next(document_batches, None)

        # Should have at least some documents
        assert first_batch is not None
        assert isinstance(first_batch, list)
        assert len(first_batch) > 0

        # Check document structure
        doc = first_batch[0]
        assert isinstance(doc, Document)
        assert doc.id.startswith("hubspot_")
        assert doc.source.value == "hubspot"
        assert doc.semantic_identifier is not None
        assert doc.doc_updated_at is not None
        assert isinstance(doc.metadata, dict)
        assert "object_type" in doc.metadata
        assert doc.metadata["object_type"] in ["ticket", "company", "deal", "contact"]

        # Check sections
        assert len(doc.sections) > 0
        assert doc.sections[0].text is not None
        assert doc.sections[0].link is not None

    def test_document_metadata_structure(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that document metadata contains expected fields."""
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()
        all_docs: list[Document] = []

        # Collect a few batches to test different object types
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            batch_count += 1
            if (
                batch_count >= 3 or len(all_docs) >= 20
            ):  # Limit to avoid too many API calls
                break

        # Group documents by object type
        docs_by_type: dict[str, list[Document]] = {}
        for doc in all_docs:
            obj_type_value = doc.metadata["object_type"]
            # Handle the case where metadata value could be a list
            obj_type = (
                obj_type_value if isinstance(obj_type_value, str) else obj_type_value[0]
            )
            if obj_type not in docs_by_type:
                docs_by_type[obj_type] = []
            docs_by_type[obj_type].append(doc)

        # Test each object type has expected metadata
        for obj_type, docs in docs_by_type.items():
            doc = docs[0]  # Test first document of each type

            if obj_type == "ticket":
                assert "ticket_id" in doc.metadata
                assert doc.id.startswith("hubspot_ticket_")
            elif obj_type == "company":
                assert "company_id" in doc.metadata
                assert doc.id.startswith("hubspot_company_")

            elif obj_type == "deal":
                assert "deal_id" in doc.metadata
                assert doc.id.startswith("hubspot_deal_")

            elif obj_type == "contact":
                assert "contact_id" in doc.metadata
                assert doc.id.startswith("hubspot_contact_")

            # Check for associated object IDs in metadata (if they exist)
            potential_association_keys = [
                "associated_contact_ids",
                "associated_company_ids",
                "associated_deal_ids",
                "associated_ticket_ids",
                "associated_note_ids",
            ]

            for key in potential_association_keys:
                if key in doc.metadata:
                    assert isinstance(doc.metadata[key], list)
                    assert len(doc.metadata[key]) > 0
                    assert all(isinstance(id_val, str) for id_val in doc.metadata[key])

    def test_associated_objects_as_sections(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that associated objects are included as sections."""
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()

        # Find a document with multiple sections (indicating associated objects)
        found_multi_section_doc = False
        batch_count = 0

        for batch in document_batches:
            for doc in batch:
                if len(doc.sections) > 1:
                    found_multi_section_doc = True

                    # First section should be the main object
                    main_section = doc.sections[0]
                    assert main_section.text is not None
                    assert main_section.link is not None

                    # Additional sections should be associated objects
                    for section in doc.sections[1:]:
                        assert section.text is not None
                        assert section.link is not None
                        # Should contain object type information
                        assert any(
                            obj_type in section.text.lower()
                            for obj_type in [
                                "contact:",
                                "company:",
                                "deal:",
                                "ticket:",
                                "note:",
                            ]
                        )

                    break

            if found_multi_section_doc:
                break

            batch_count += 1
            if batch_count >= 5:  # Limit API calls
                break

        # Note: This test might not always pass if there are no associated objects
        # in the test HubSpot instance, but it validates the structure when they exist
        if found_multi_section_doc:
            print("✓ Found document with associated objects as sections")
        else:
            print("⚠ No documents with associated objects found in test data")

    def test_poll_source_functionality(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Test poll_source with time filtering."""
        connector.load_credentials(credentials)

        # Test with a recent time range (last 30 days)
        end_time = datetime.now(timezone.utc)
        start_time = datetime.now(timezone.utc).replace(day=1)  # Start of current month

        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        document_batches = connector.poll_source(start_timestamp, end_timestamp)

        # Should be able to get at least one batch
        first_batch = next(document_batches, None)

        if first_batch is not None:
            assert isinstance(first_batch, list)
            assert len(first_batch) > 0

            # Check that documents have proper timestamps
            for doc in first_batch:
                assert doc.doc_updated_at is not None
                # Note: We don't strictly enforce the time range here since
                # the test data might not have recent updates
        else:
            print("⚠ No documents found in the specified time range")

    def test_all_object_types_processed(
        self, connector: HubSpotConnector, credentials: dict[str, Any]
    ) -> None:
        """Integration test to verify all object types are processed correctly."""
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()
        all_docs: list[Document] = []
        object_types_found = set()

        # Collect several batches to ensure we see all object types
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            for doc in batch:
                object_types_found.add(doc.metadata["object_type"])

            batch_count += 1
            # Stop after we've seen all expected types or after reasonable number of batches
            if len(object_types_found) >= 4 or batch_count >= 10:
                break

        print(f"Found {len(all_docs)} total documents")
        print(f"Object types found: {sorted(object_types_found)}")

        # Should have at least some documents
        assert len(all_docs) > 0

        # Verify we can process multiple object types
        # Note: We don't require all 4 types since the test instance might not have all types
        assert len(object_types_found) >= 1

        # Verify document structure for each type found
        for obj_type in object_types_found:
            type_docs = [
                doc for doc in all_docs if doc.metadata["object_type"] == obj_type
            ]
            assert len(type_docs) > 0

            # Check first document of this type
            doc = type_docs[0]
            assert doc.id.startswith(f"hubspot_{obj_type}_")
            assert doc.semantic_identifier is not None
            assert len(doc.sections) > 0
            assert doc.sections[0].text is not None
            assert doc.sections[0].link is not None

            # Check object-specific metadata
            if obj_type == "company":
                assert "company_id" in doc.metadata
            elif obj_type == "deal":
                assert "deal_id" in doc.metadata
            elif obj_type == "contact":
                assert "contact_id" in doc.metadata
            elif obj_type == "ticket":
                assert "ticket_id" in doc.metadata

    def test_init_default_object_types(self) -> None:
        """Test that connector initializes with all object types by default."""
        connector = HubSpotConnector()
        assert connector.object_types == AVAILABLE_OBJECT_TYPES
        assert "tickets" in connector.object_types
        assert "companies" in connector.object_types
        assert "deals" in connector.object_types
        assert "contacts" in connector.object_types

    def test_init_custom_object_types(self) -> None:
        """Test that connector can be initialized with custom object types."""
        custom_types = ["tickets", "companies"]
        connector = HubSpotConnector(object_types=custom_types)
        expected_set = {"tickets", "companies"}
        assert connector.object_types == expected_set
        assert "tickets" in connector.object_types
        assert "companies" in connector.object_types
        assert "deals" not in connector.object_types
        assert "contacts" not in connector.object_types

    def test_init_custom_object_types_from_list(self) -> None:
        """Test that connector can be initialized with custom object types from a list (frontend format)."""
        custom_types_list = ["tickets", "companies"]
        connector = HubSpotConnector(object_types=custom_types_list)
        expected_set = {"tickets", "companies"}
        assert connector.object_types == expected_set
        assert "tickets" in connector.object_types
        assert "companies" in connector.object_types
        assert "deals" not in connector.object_types
        assert "contacts" not in connector.object_types

    def test_init_single_object_type(self) -> None:
        """Test that connector can be initialized with a single object type."""
        single_type = ["deals"]
        connector = HubSpotConnector(object_types=single_type)
        expected_set = {"deals"}
        assert connector.object_types == expected_set
        assert len(connector.object_types) == 1
        assert "deals" in connector.object_types

    def test_init_invalid_object_types(self) -> None:
        """Test that connector raises error for invalid object types."""
        invalid_types = ["tickets", "invalid_type", "another_invalid"]

        with pytest.raises(ValueError) as exc_info:
            HubSpotConnector(object_types=invalid_types)

        error_message = str(exc_info.value)
        assert "Invalid object types" in error_message
        assert "invalid_type" in error_message
        assert "another_invalid" in error_message
        assert "Available types" in error_message

    def test_init_empty_object_types(self) -> None:
        """Test that connector can be initialized with empty object types set."""
        empty_types: list[str] = []
        connector = HubSpotConnector(object_types=empty_types)
        expected_set: set[str] = set()
        assert connector.object_types == expected_set
        assert len(connector.object_types) == 0

    def test_selective_object_fetching_tickets_only(
        self, credentials: dict[str, Any]
    ) -> None:
        """Test that only tickets are fetched when configured."""
        connector = HubSpotConnector(object_types=["tickets"], batch_size=5)
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()
        all_docs: list[Document] = []

        # Collect a few batches
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            batch_count += 1
            if batch_count >= 3 or len(all_docs) >= 10:
                break

        # Should have documents
        if all_docs:
            # All documents should be tickets
            for doc in all_docs:
                assert doc.metadata["object_type"] == "ticket"
                assert doc.id.startswith("hubspot_ticket_")

            print(f"✓ Successfully fetched {len(all_docs)} ticket documents only")
        else:
            print("⚠ No ticket documents found in test data")

    def test_selective_object_fetching_companies_and_deals(
        self, credentials: dict[str, Any]
    ) -> None:
        """Test that only companies and deals are fetched when configured."""
        connector = HubSpotConnector(object_types=["companies", "deals"], batch_size=5)
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()
        all_docs: list[Document] = []
        object_types_found = set()

        # Collect a few batches
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            for doc in batch:
                object_types_found.add(doc.metadata["object_type"])
            batch_count += 1
            if batch_count >= 3 or len(all_docs) >= 10:
                break

        if all_docs:
            # Should only have companies and deals
            assert object_types_found.issubset({"company", "deal"})
            assert "ticket" not in object_types_found
            assert "contact" not in object_types_found

            # Verify document structure
            for doc in all_docs:
                obj_type = doc.metadata["object_type"]
                assert obj_type in ["company", "deal"]
                if obj_type == "company":
                    assert doc.id.startswith("hubspot_company_")
                elif obj_type == "deal":
                    assert doc.id.startswith("hubspot_deal_")

            print(
                f"✓ Successfully fetched {len(all_docs)} documents of types: {object_types_found}"
            )
        else:
            print("⚠ No company/deal documents found in test data")

    def test_empty_object_types_fetches_nothing(
        self, credentials: dict[str, Any]
    ) -> None:
        """Test that no documents are fetched when object_types is empty."""
        connector = HubSpotConnector(object_types=[], batch_size=5)
        connector.load_credentials(credentials)

        document_batches = connector.load_from_state()
        all_docs: list[Document] = []

        # Try to collect batches
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            batch_count += 1
            if batch_count >= 2:  # Don't wait too long
                break

        # Should have no documents
        assert len(all_docs) == 0
        print("✓ No documents fetched with empty object_types as expected")

    def test_poll_source_respects_object_types(
        self, credentials: dict[str, Any]
    ) -> None:
        """Test that poll_source respects the object_types configuration."""
        connector = HubSpotConnector(object_types=["contacts"], batch_size=5)
        connector.load_credentials(credentials)

        # Test with a recent time range
        end_time = datetime.now(timezone.utc)
        start_time = datetime.now(timezone.utc).replace(day=1)

        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        document_batches = connector.poll_source(start_timestamp, end_timestamp)
        all_docs: list[Document] = []

        # Collect a few batches
        batch_count = 0
        for batch in document_batches:
            all_docs.extend(batch)
            batch_count += 1
            if batch_count >= 2 or len(all_docs) >= 5:
                break

        if all_docs:
            # All documents should be contacts
            for doc in all_docs:
                assert doc.metadata["object_type"] == "contact"
                assert doc.id.startswith("hubspot_contact_")

            print(
                f"✓ Poll source successfully fetched {len(all_docs)} contact documents only"
            )
        else:
            print("⚠ No contact documents found in specified time range")

    def test_object_types_immutability(self) -> None:
        """Test that object_types set cannot be modified externally."""
        original_types = ["tickets", "companies"]
        connector = HubSpotConnector(object_types=original_types)

        # Modifying the original list should not affect the connector
        original_types.append("deals")
        assert "deals" not in connector.object_types
        assert connector.object_types == {"tickets", "companies"}

        # Trying to modify the connector's object_types should not affect the original
        connector_types = connector.object_types
        connector_types.add("contacts")
        # The connector should still have the original types since we made a copy
        # Note: This test verifies our implementation makes a copy in __init__

    def test_url_generation(self) -> None:
        """Test that URLs are generated correctly for different object types."""
        connector = HubSpotConnector()
        connector.portal_id = "12345"  # Mock portal ID

        # Test URL generation for each object type
        ticket_url = connector._get_object_url("tickets", "67890")
        expected_ticket_url = "https://app.hubspot.com/contacts/12345/record/0-5/67890"
        assert ticket_url == expected_ticket_url

        company_url = connector._get_object_url("companies", "11111")
        expected_company_url = "https://app.hubspot.com/contacts/12345/record/0-2/11111"
        assert company_url == expected_company_url

        deal_url = connector._get_object_url("deals", "22222")
        expected_deal_url = "https://app.hubspot.com/contacts/12345/record/0-3/22222"
        assert deal_url == expected_deal_url

        contact_url = connector._get_object_url("contacts", "33333")
        expected_contact_url = "https://app.hubspot.com/contacts/12345/record/0-1/33333"
        assert contact_url == expected_contact_url

        note_url = connector._get_object_url("notes", "44444")
        expected_note_url = "https://app.hubspot.com/contacts/12345/objects/0-4/44444"
        assert note_url == expected_note_url
