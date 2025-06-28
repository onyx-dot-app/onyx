import os

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.outline.connector import OutlineConnector


@pytest.fixture
def outline_connector() -> OutlineConnector:
    connector = OutlineConnector()
    connector.load_credentials(
        {
            "outline_base_url": os.environ.get("OUTLINE_BASE_URL", ""),
            "outline_api_token": os.environ.get("OUTLINE_API_TOKEN", ""),
        }
    )
    return connector


def test_outline_connector_basic(outline_connector: OutlineConnector) -> None:
    """Test basic functionality of the Outline connector"""

    # Test validation
    outline_connector.validate_connector_settings()

    # Test loading documents
    all_docs = []
    batch_count = 0
    for doc_batch in outline_connector.load_from_state():
        batch_count += 1
        all_docs.extend(doc_batch)
        # Ensure batches aren't empty
        assert len(doc_batch) > 0, f"Batch {batch_count} should not be empty"

    assert len(all_docs) > 0, "Should have found at least one document"
    assert batch_count > 0, "Should have processed at least one batch"

    # Check document structure for all documents
    doc_ids = set()
    for doc in all_docs:
        # Basic document validation
        assert doc.id is not None, "Document ID should not be None"
        assert doc.id != "", "Document ID should not be empty"
        assert doc.title is not None, "Document title should not be None"
        assert doc.title != "", "Document title should not be empty"
        assert (
            doc.source.value == "outline"
        ), f"Document source should be 'outline', got {doc.source.value}"

        # Check for duplicate IDs
        assert doc.id not in doc_ids, f"Duplicate document ID found: {doc.id}"
        doc_ids.add(doc.id)

        # Sections validation
        assert (
            len(doc.sections) > 0
        ), f"Document {doc.id} should have at least one section"
        for i, section in enumerate(doc.sections):
            # section.text is required for TextSection, so it cannot be None
            assert (
                section.text is not None
            ), f"Section {i} text should not be None in document {doc.id}"
            assert (
                section.text.strip() != ""
            ), f"Section {i} text should not be empty in document {doc.id}"
            assert section.link.startswith(
                "http"
            ), f"Section {i} link should be a valid URL in document {doc.id}"

        # Metadata validation
        assert (
            "type" in doc.metadata
        ), f"Document {doc.id} should have 'type' in metadata"
        doc_type = doc.metadata["type"]
        assert doc_type in [
            "collection",
            "document",
        ], f"Document type should be 'collection' or 'document', got {doc_type}"

        # Semantic identifier validation
        assert (
            doc.semantic_identifier is not None
        ), f"Document {doc.id} should have semantic_identifier"
        if doc_type == "collection":
            assert doc.semantic_identifier.startswith(
                "Collection: "
            ), "Collection semantic_identifier should start with 'Collection: '"
            assert doc.id.startswith(
                "collection:"
            ), "Collection ID should start with 'collection:'"
        elif doc_type == "document":
            assert doc.semantic_identifier.startswith(
                "Document: "
            ), "Document semantic_identifier should start with 'Document: '"
            assert doc.id.startswith(
                "document:"
            ), "Document ID should start with 'document:'"

            # Document-specific metadata checks
            assert (
                "collection_id" in doc.metadata
            ), f"Document {doc.id} should have collection_id in metadata"
            assert (
                "template" in doc.metadata
            ), f"Document {doc.id} should have template in metadata"
            assert (
                "archived" in doc.metadata
            ), f"Document {doc.id} should have archived in metadata"

            # Validate metadata types (should be strings after our fix)
            # Use direct access and type checking without intermediate variables
            assert isinstance(
                doc.metadata["template"], str
            ), f"template should be string, got {type(doc.metadata['template'])}"
            assert isinstance(
                doc.metadata["archived"], str
            ), f"archived should be string, got {type(doc.metadata['archived'])}"
            # Now we can safely use the values since we've asserted they are strings
            assert doc.metadata["template"] in [
                "true",
                "false",
            ], f"template should be 'true' or 'false', got {doc.metadata['template']}"
            assert doc.metadata["archived"] in [
                "true",
                "false",
            ], f"archived should be 'true' or 'false', got {doc.metadata['archived']}"


def test_outline_connector_incremental(outline_connector: OutlineConnector) -> None:
    """Test incremental polling functionality"""
    import time
    from datetime import datetime, timezone

    # Get documents from the last 7 days
    end_time = time.time()
    start_time = end_time - (7 * 24 * 60 * 60)  # 7 days ago

    recent_docs = []
    batch_count = 0
    for doc_batch in outline_connector.poll_source(start_time, end_time):
        batch_count += 1
        recent_docs.extend(doc_batch)
        # Ensure batches aren't empty if we get any
        if doc_batch:
            assert (
                len(doc_batch) > 0
            ), f"Non-empty batch {batch_count} should have documents"

    # Should be able to run without errors (may or may not have recent documents)
    assert isinstance(recent_docs, list), "Should return a list of documents"
    print(f"Found {len(recent_docs)} recent documents in {batch_count} batches")

    # If there are recent documents, they should have proper structure
    if recent_docs:
        start_datetime = datetime.fromtimestamp(start_time, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end_time, tz=timezone.utc)

        for doc in recent_docs:
            # Basic validation
            assert doc.id is not None, "Recent document should have ID"
            assert doc.title is not None, "Recent document should have title"
            assert (
                doc.source.value == "outline"
            ), "Recent document should have correct source"

            # Time validation - should be within our range
            assert (
                doc.doc_updated_at is not None
            ), f"Recent document {doc.id} should have update timestamp"

            # Handle timezone-aware vs naive datetime comparison
            doc_updated_at = doc.doc_updated_at
            if doc_updated_at.tzinfo is None:
                # If doc timestamp is naive, make comparison datetimes naive too
                start_datetime = datetime.fromtimestamp(start_time)
                end_datetime = datetime.fromtimestamp(end_time)
            else:
                # If doc timestamp is aware, ensure our comparison datetimes are aware
                if start_datetime.tzinfo is None:
                    start_datetime = start_datetime.replace(tzinfo=timezone.utc)
                if end_datetime.tzinfo is None:
                    end_datetime = end_datetime.replace(tzinfo=timezone.utc)

            assert (
                doc_updated_at >= start_datetime
            ), f"Document {doc.id} updated_at ({doc_updated_at}) should be after start time ({start_datetime})"
            assert (
                doc_updated_at <= end_datetime
            ), f"Document {doc.id} updated_at ({doc_updated_at}) should be before end time ({end_datetime})"

            # Metadata validation
            assert (
                "type" in doc.metadata
            ), f"Recent document {doc.id} should have type metadata"

    # Test with a very recent time range (last hour)
    very_recent_start = end_time - (60 * 60)  # 1 hour ago
    very_recent_docs = []
    for doc_batch in outline_connector.poll_source(very_recent_start, end_time):
        very_recent_docs.extend(doc_batch)

    # Very recent docs should be a subset of recent docs (or same)
    assert len(very_recent_docs) <= len(
        recent_docs
    ), "Very recent docs should be subset of recent docs"


def test_outline_connector_document_types(outline_connector: OutlineConnector) -> None:
    """Test that different document types are handled correctly"""

    all_docs = []
    for doc_batch in outline_connector.load_from_state():
        all_docs.extend(doc_batch)
        # Limit for testing to avoid long test times
        if len(all_docs) >= 20:
            break

    assert len(all_docs) > 0, "Should have at least some documents for type testing"

    collections = []
    documents = []

    # Check document metadata and categorize
    for doc in all_docs:
        assert "type" in doc.metadata, f"Document {doc.id} should have type in metadata"
        doc_type = doc.metadata["type"]
        assert doc_type in [
            "collection",
            "document",
        ], f"Document type should be valid, got {doc_type}"

        if doc_type == "document":
            documents.append(doc)
            # Document-specific checks
            assert (
                "collection_id" in doc.metadata
            ), f"Document {doc.id} should have collection_id in metadata"
            assert (
                "template" in doc.metadata
            ), f"Document {doc.id} should have template in metadata"
            assert (
                "archived" in doc.metadata
            ), f"Document {doc.id} should have archived in metadata"
            assert doc.id.startswith(
                "document:"
            ), f"Document ID should start with 'document:', got {doc.id}"

            # Validate collection_id format
            collection_id_raw = doc.metadata.get("collection_id")
            if collection_id_raw is not None:
                assert isinstance(
                    collection_id_raw, str
                ), f"collection_id should be string, got {type(collection_id_raw)}"

            # Check URL format for documents
            first_section = doc.sections[0]
            if first_section.link is not None:
                assert (
                    "/doc/" in first_section.link
                ), f"Document URL should contain '/doc/', got {first_section.link}"

        elif doc_type == "collection":
            collections.append(doc)
            # Collection-specific checks
            assert doc.id.startswith(
                "collection:"
            ), f"Collection ID should start with 'collection:', got {doc.id}"

            # Check URL format for collections (Outline uses collection ID directly in URL)
            first_section = doc.sections[0]
            if first_section.link is not None:
                # Collection URLs contain the collection ID as a UUID in the path
                collection_id = doc.id.replace("collection:", "")
                assert (
                    collection_id in first_section.link
                ), f"Collection URL should contain collection ID {collection_id}, got {first_section.link}"

    print(f"Found {len(collections)} collections and {len(documents)} documents")

    # Validate we have reasonable content
    if collections:
        # Test collection properties
        sample_collection = collections[0]
        sample_title = sample_collection.title
        assert (
            sample_title is not None and len(sample_title) > 0
        ), "Collection should have non-empty title"
        sample_semantic_id = sample_collection.semantic_identifier
        assert sample_semantic_id is not None and sample_semantic_id.startswith(
            "Collection: "
        ), "Collection semantic identifier format"

    if documents:
        # Test document properties
        sample_document = documents[0]
        sample_doc_title = sample_document.title
        assert (
            sample_doc_title is not None and len(sample_doc_title) > 0
        ), "Document should have non-empty title"
        sample_doc_semantic_id = sample_document.semantic_identifier
        assert sample_doc_semantic_id is not None and sample_doc_semantic_id.startswith(
            "Document: "
        ), "Document semantic identifier format"

        # Check for variety in template/archived status
        template_values = set(str(doc.metadata["template"]) for doc in documents)
        archived_values = set(str(doc.metadata["archived"]) for doc in documents)

        # Should have valid boolean string values
        assert template_values.issubset(
            {"true", "false"}
        ), f"Template values should be boolean strings, got {template_values}"
        assert archived_values.issubset(
            {"true", "false"}
        ), f"Archived values should be boolean strings, got {archived_values}"

    # Ensure we have at least one type
    assert (
        len(collections) > 0 or len(documents) > 0
    ), "Should have either collections or documents"


def test_outline_connector_error_handling(outline_connector: OutlineConnector) -> None:
    """Test error handling and edge cases"""

    # Test with invalid credentials
    bad_connector = OutlineConnector()
    bad_connector.load_credentials(
        {
            "outline_base_url": "https://invalid-outline-instance.com",
            "outline_api_token": "invalid_token_12345",
        }
    )

    # Should raise validation error for bad credentials
    with pytest.raises(
        (CredentialExpiredError, ConnectorValidationError, InsufficientPermissionsError)
    ):
        bad_connector.validate_connector_settings()

    # Test with malformed URL
    malformed_connector = OutlineConnector()
    malformed_connector.load_credentials(
        {
            "outline_base_url": "not-a-valid-url",
            "outline_api_token": "some_token",
        }
    )

    with pytest.raises(ConnectorValidationError):
        malformed_connector.validate_connector_settings()


def test_outline_connector_content_quality(outline_connector: OutlineConnector) -> None:
    """Test the quality and completeness of extracted content"""

    all_docs = []
    for doc_batch in outline_connector.load_from_state():
        all_docs.extend(doc_batch)
        if len(all_docs) >= 10:  # Sample size for content quality testing
            break

    assert len(all_docs) > 0, "Need documents to test content quality"

    documents = [doc for doc in all_docs if doc.metadata.get("type") == "document"]

    if documents:
        for doc in documents[:5]:  # Test first 5 documents
            text_content = doc.sections[0].text

            # Content quality checks
            assert (
                text_content is not None
            ), f"Document {doc.id} should have non-null text content"
            assert (
                len(text_content.strip()) > 0
            ), f"Document {doc.id} should have non-empty text content"

            # Type narrowing: after the None check, mypy knows text_content is str
            doc_title = doc.title
            assert (
                doc_title is not None
            ), f"Document {doc.id} should have non-null title"
            assert len(text_content) > len(
                doc_title
            ), f"Document {doc.id} content should be longer than just title"

            # Check for markdown-style content (if present)
            if "#" in text_content or "*" in text_content or "```" in text_content:
                print(f"Document {doc.title} appears to contain markdown formatting")

            # Ensure title is included in content
            # We already checked that both text_content and doc_title are not None above
            title_in_content = doc_title.lower() in text_content.lower()
            assert (
                title_in_content
            ), f"Document {doc.id} title should appear somewhere in content"

            # URL validation
            doc_url = doc.sections[0].link
            if doc_url is not None:
                assert doc_url.startswith(
                    "http"
                ), f"Document URL should be valid HTTP URL, got {doc_url}"
                assert (
                    "outline" in doc_url.lower()
                ), f"Document URL should contain 'outline', got {doc_url}"


def test_outline_connector_pagination(outline_connector: OutlineConnector) -> None:
    """Test that pagination works correctly"""

    # Create a connector with small batch size to test pagination
    small_batch_connector = OutlineConnector(batch_size=2)
    small_batch_connector.load_credentials(
        {
            "outline_base_url": os.environ.get("OUTLINE_BASE_URL", ""),
            "outline_api_token": os.environ.get("OUTLINE_API_TOKEN", ""),
        }
    )

    all_docs = []
    batch_sizes = []

    for doc_batch in small_batch_connector.load_from_state():
        batch_sizes.append(len(doc_batch))
        all_docs.extend(doc_batch)

        # Stop after a reasonable number for testing
        if len(all_docs) >= 10:
            break

    if len(all_docs) > 2:  # Only test if we have enough documents
        # Should have multiple batches with small batch size
        assert (
            len(batch_sizes) > 1
        ), f"Should have multiple batches, got {len(batch_sizes)} batches with sizes {batch_sizes}"

        # Most batches should be size 2 (except possibly the last one)
        for i, size in enumerate(batch_sizes[:-1]):  # All except last batch
            assert size <= 2, f"Batch {i} size should be <= 2, got {size}"

    print(f"Pagination test: {len(batch_sizes)} batches with sizes {batch_sizes}")


if __name__ == "__main__":
    # For manual testing - set environment variables first
    # OUTLINE_BASE_URL=https://your-team.getoutline.com
    # OUTLINE_API_TOKEN=your_api_token_here

    if not os.environ.get("OUTLINE_BASE_URL") or not os.environ.get(
        "OUTLINE_API_TOKEN"
    ):
        print("Please set OUTLINE_BASE_URL and OUTLINE_API_TOKEN environment variables")
        exit(1)

    connector = OutlineConnector()
    connector.load_credentials(
        {
            "outline_base_url": os.environ["OUTLINE_BASE_URL"],
            "outline_api_token": os.environ["OUTLINE_API_TOKEN"],
        }
    )

    print("Testing Outline connector...")

    try:
        connector.validate_connector_settings()
        print("✓ Connector validation passed")
    except Exception as e:
        print(f"✗ Connector validation failed: {e}")
        exit(1)

    try:
        all_docs = []
        for doc_batch in connector.load_from_state():
            all_docs.extend(doc_batch)
            if len(all_docs) >= 10:  # Limit for testing
                break

        print(f"✓ Successfully loaded {len(all_docs)} documents")

        if all_docs:
            first_doc = all_docs[0]
            print(
                f"✓ Sample document: {first_doc.title} (type: {first_doc.metadata.get('type')})"
            )

    except Exception as e:
        print(f"✗ Document loading failed: {e}")
        exit(1)

    print("All tests passed!")
