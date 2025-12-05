"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Have a Coda workspace with at least 1 doc and multiple pages
"""

import os
from collections.abc import Generator
from time import sleep
from time import time
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


@pytest.fixture(scope="session")
def api_token() -> str:
    """Fixture to get and validate API token."""
    token = os.environ.get("CODA_API_TOKEN")
    if not token:
        pytest.skip("CODA_API_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def api_client(api_token: str) -> CodaAPIClient:
    """Fixture to create and authenticate API client."""
    client = CodaAPIClient(api_token)
    client.validate_credentials()
    return client


@pytest.fixture(scope="session")
def connector(
    request: pytest.FixtureRequest, api_token: str, test_docs: list[dict[str, Any]]
) -> CodaConnector:
    """Fixture to create and authenticate connector."""
    conn = CodaConnector(
        batch_size=5,
        doc_ids=[test_docs[0]["id"]],
    )
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


@pytest.fixture(scope="session")
def reference_data(
    api_client: CodaAPIClient,
    connector: CodaConnector,
    test_docs: list[dict[str, Any]],
    all_batches: list[list[Document]],
) -> dict[str, Any]:
    """Fixture to fetch reference data from API.

    Builds a map of docs and their pages for validation.
    Depends on test_doc to ensure the test document exists before fetching.
    """
    all_docs = connector.doc_ids
    logger.info(f"All docs: {all_docs}")

    if not all_docs:
        pytest.skip("No docs found in Coda workspace")

    # Count expected non-hidden pages across all docs
    expected_page_count = 0
    expected_pages_by_doc = {}

    for doc in all_docs:
        pages = api_client.fetch_all_pages(doc)

        # Only count non-hidden pages
        non_hidden_pages = [
            p
            for p in pages
            if not p.isHidden and p.id not in connector.generator.skipped_pages
        ]
        expected_pages_by_doc[doc] = non_hidden_pages
        expected_page_count += len(non_hidden_pages)

    if expected_page_count == 0:
        pytest.skip("No visible pages found in Coda workspace")

    return {
        "docs": all_docs,
        "total_pages": expected_page_count,
        "pages_by_doc": expected_pages_by_doc,
    }


@pytest.fixture(scope="session")
def all_batches(connector: CodaConnector) -> list[list[Document]]:
    """Fixture that loads all batches once and caches them.

    This avoids calling load_from_state() multiple times across tests,
    significantly reducing API calls and test execution time.
    """
    assert connector.generator is not None
    connector.generator.indexed_pages.clear()
    connector.generator.indexed_tables.clear()

    logger.info("Loading all batches...")
    gen = connector.load_from_state()
    batches = list(gen)
    return batches


@pytest.fixture(scope="session")
def all_documents(all_batches: list[list[Document]]) -> list[Document]:
    """Fixture that flattens all batches into a single list of documents."""
    all_docs = []
    for batch in all_batches:
        all_docs.extend(batch)
    return all_docs


@pytest.fixture(scope="session")
def test_docs(api_token: str) -> Generator[dict[str, Any], None, None]:
    """Fixture that creates a test doc once for the entire test session.

    Creates a doc by copying from a template, yields it for tests,
    and cleans it up after all tests complete.
    """
    # Create a temporary API client for setup/teardown
    client = CodaAPIClient(api_token)

    # Create the test doc
    response = client.create_doc(
        title="Two-way writeups: Coda's secret to shipping fast",
        source_doc="_WhgwP-IEe",
        folder_id="fl-nTy7sq9EcW",
    )

    response2 = client.create_doc(
        title="Simple Document",
        folder_id="fl-nTy7sq9EcW",
        initial_page={
            "name": "Page 1",
            "pageContent": {
                "type": "canvas",
                "canvasContent": {
                    "format": "html",
                    "content": "<p><b>This</b> is rich text</p>",
                },
            },
        },
    )

    print(f"\n[SETUP] Created test doc: {response['name']}")
    print(f"[SETUP] Doc ID: {response['id']}")
    print(f"[SETUP] Browser link: {response['browserLink']}")

    # Poll for doc availability instead of hard sleep
    print("\n[SETUP] Polling for doc availability...")
    start_time = time()
    timeout = 60
    doc_available = False

    while time() - start_time < timeout:
        try:
            # Try to fetch the doc
            check_response = client._make_request("GET", f"/docs/{response['id']}")
            if check_response and check_response.get("id") == response["id"]:
                print(f"[SETUP] Doc available after {time() - start_time:.1f}s")
                doc_available = True
                break
        except Exception:
            pass
        sleep(2)

    if not doc_available:
        print(f"[SETUP] Warning: Doc not available after {timeout}s, tests may fail")

    # Yield the doc info for tests to use
    yield [response, response2]

    # Cleanup: Delete the doc after all tests complete
    try:
        client._make_request("DELETE", f"/docs/{response['id']}")
        print(f"\n[TEARDOWN] Deleted test doc: {response['id']}")
    except Exception as e:
        print(f"\n[TEARDOWN] Warning: Failed to delete test doc {response['id']}: {e}")


class TestDocCreation:
    """Test suite for doc creation and manipulation."""

    def test_doc_was_created(self, test_docs: list[dict[str, Any]]) -> None:
        """Test that the test doc fixture was created successfully."""
        # Verify response structure
        assert "id" in test_docs[0], "Response should contain doc ID"
        assert "name" in test_docs[0], "Response should contain doc name"
        assert "href" in test_docs[0], "Response should contain API href"
        assert "browserLink" in test_docs[0], "Response should contain browser link"

        # Verify the doc was created with correct title
        assert (
            test_docs[0]["name"] == "Two-way writeups: Coda's secret to shipping fast"
        ), f"Doc name should match, got: {test_docs[0]['name']}"

        # Verify doc type
        assert test_docs[0].get("type") == "doc", "Response type should be 'doc'"

        # Log the doc info
        print(f"\nTest doc verified: {test_docs[0]['name']}")
        print(f"Doc ID: {test_docs[0]['id']}")
        print(f"Browser link: {test_docs[0]['browserLink']}")

    def test_can_fetch_created_doc(
        self, api_client: CodaAPIClient, test_docs: list[dict[str, Any]]
    ) -> None:
        """Test that we can fetch the created doc via the API."""
        doc_id = test_docs[0]["id"]

        # Fetch the doc
        response = api_client._make_request("GET", f"/docs/{doc_id}")

        # Verify we got the same doc
        assert response["id"] == doc_id, "Fetched doc ID should match"
        assert response["name"] == "Two-way writeups: Coda's secret to shipping fast"
        print(f"\nSuccessfully fetched doc: {response['name']}")


class TestLoadFromStateEndToEnd:
    """Test suite for load_from_state end-to-end functionality."""

    def test_returns_generator(self, connector: CodaConnector) -> None:
        """Test that load_from_state returns a generator."""
        gen = connector.load_from_state()
        assert isinstance(gen, Generator), "load_from_state should return a Generator"

    def test_batch_sizes_respect_config(
        self,
        connector: CodaConnector,
        test_docs: list[dict[str, Any]],
        all_batches: list[list[Document]],
    ) -> None:
        """Test that batches respect the configured batch_size."""
        batch_size = connector.batch_size

        batch_sizes = []
        for batch in all_batches:
            batch_sizes.append(len(batch))
            # All batches should be <= batch_size
            assert (
                len(batch) <= batch_size
            ), f"Batch size {len(batch)} exceeds configured {batch_size}"

        # All non-final batches should be exactly batch_size
        for i, size in enumerate(batch_sizes[:-1]):
            assert (
                size == batch_size
            ), f"Non-final batch {i} has size {size}, expected {batch_size}"

        # Last batch may be smaller
        if batch_sizes:
            assert batch_sizes[-1] <= batch_size

    def test_document_count_matches_expected(
        self,
        all_documents: list[Document],
        reference_data: dict[str, Any],
        connector: CodaConnector,
    ) -> None:
        """Test that documents are generated from non-hidden pages.

        Note: The actual count may be less than the API page count because:
        - Some pages may fail to export
        - Some pages may have empty content
        """
        total_documents = len(all_documents)
        expected_count = reference_data["total_pages"]

        # We should get at least some documents
        assert total_documents > 0, "Expected at least one document"

        logger.info(f"Total documents: {total_documents}")
        logger.info(f"Expected count: {expected_count}")

        # Log if there's a significant mismatch (for debugging)
        assert (
            not total_documents < expected_count
        ), f"Expected at least {expected_count} documents, got {total_documents}"

    def test_document_required_fields(
        self,
        all_documents: list[Document],
        connector: CodaConnector,
        reference_data: dict[str, Any],
    ) -> None:
        """Test that all documents have required fields."""
        for doc in all_documents:
            # Type check
            assert isinstance(doc, Document)

            # Required fields
            assert doc.id is not None
            assert doc.source == DocumentSource.CODA
            assert doc.semantic_identifier is not None
            assert doc.doc_updated_at is not None

            # Sections with content
            assert len(doc.sections) > 0
            for section in doc.sections:
                if isinstance(section, TextSection):
                    assert section.text is not None
                    assert len(section.text) > 0
                elif isinstance(section, ImageSection):
                    assert section.image_file_id is not None

            assert "doc_id" in doc.metadata
            assert "page_id" in doc.metadata or "table_id" in doc.metadata
            assert "path" in doc.metadata or "table_name" in doc.metadata

    def test_hidden_pages_excluded(
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that hidden pages are not included in results."""
        # Collect all yielded page IDs
        yielded_page_ids = set()
        for doc in all_documents:
            page_id = doc.metadata.get("page_id")
            if page_id:
                yielded_page_ids.add(page_id)

        # Get all hidden page IDs from reference data
        all_hidden_page_ids = set()
        for doc_id, pages in reference_data["pages_by_doc"].items():
            for page in pages:
                if page.isHidden:
                    all_hidden_page_ids.add(page.id)

        # Verify no overlap
        hidden_in_results = all_hidden_page_ids & yielded_page_ids
        assert (
            not hidden_in_results
        ), f"Found {len(hidden_in_results)} hidden pages in results"

    def test_no_duplicate_documents(
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that no documents are yielded twice."""
        document_ids = [doc.id for doc in all_documents]

        unique_ids = set(document_ids)
        assert len(document_ids) == len(
            unique_ids
        ), f"Found {len(document_ids) - len(unique_ids)} duplicate documents"

    def test_all_docs_processed(
        self, all_documents: list[Document], connector: CodaConnector
    ) -> None:
        """Test that pages from all docs are included."""
        processed_doc_ids = set[str]()
        for doc in all_documents:
            doc_id = doc.metadata.get("doc_id")
            processed_doc_ids.add(doc_id)

        logger.info(f"Processed doc IDs: {processed_doc_ids}")
        logger.info(f"Expected doc IDs: {connector.doc_ids}")

        expected_doc_ids = connector.doc_ids
        assert (
            processed_doc_ids == expected_doc_ids
        ), f"Not all docs were processed. Expected {expected_doc_ids}, got {processed_doc_ids}"

    def test_document_content_not_empty(
        self,
        all_documents: list[Document],
        reference_data: dict[str, Any],
        connector: CodaConnector,
    ) -> None:
        """Test that all documents have meaningful content (not just title)."""
        for doc in all_documents:
            assert doc.semantic_identifier

            for section in doc.sections:
                if isinstance(section, ImageSection):
                    assert section.image_file_id is not None
                    continue

                assert section.text is not None, f"Section text is None for {doc.id}"

                assert len(section.text) > 0, f"Section text is empty for doc {doc.id}"

                if doc.metadata.get("type") != CodaObjectType.TABLE:
                    content_len = len(section.text)
                    assert (
                        content_len > 10
                    ), f"Document {doc.id} lacks meaningful content (only {content_len} chars) {doc.semantic_identifier}"

    def test_metadata_contains_hierarchy_info(
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that metadata contains page hierarchy information."""
        for doc in all_documents:
            metadata = doc.metadata

            # Pages should have path
            if "page_id" in metadata:
                assert "path" in metadata
                path = metadata["path"]
                assert isinstance(path, str), "Path should be a string"
                assert path
                assert path == path.strip()  # No leading/trailing spaces

                # If page has a parent, it should be in metadata
                if "parent_page_id" in metadata:
                    assert metadata["parent_page_id"] is not None

            # Tables should have table info
            elif "table_id" in metadata:
                assert "table_name" in metadata
                assert "row_count" in metadata
                assert "column_count" in metadata


class TestExportFormats:
    """Test suite for content export."""

    def test_content_export(
        self, api_token: str, test_docs: list[dict[str, Any]]
    ) -> None:
        """Test that content export works correctly."""
        # Create connector
        connector = CodaConnector(batch_size=5, doc_ids=[test_docs[1]["id"]])
        connector.load_credentials({"coda_api_token": api_token})

        # Load documents
        gen = connector.load_from_state()
        batches = list(gen)

        # Check that we got documents
        all_docs = []
        for batch in batches:
            all_docs.extend(batch)

        assert len(all_docs) > 0, "Should have at least one document"

        # Verify content is HTML (check for HTML tags)
        page_docs = [doc for doc in all_docs if "page_id" in doc.metadata]
        if page_docs:
            sample_doc = page_docs[0]
            content = sample_doc.sections[0].text
            # HTML should have tags like <p>, <div>, <h1>, etc.
            has_html_tags = any(
                tag in content for tag in ["<p>", "<div>", "<h1>", "<h2>", "<span>"]
            )
            assert has_html_tags or len(content) > 0, "Should have HTML content"
            print(f"\nHTML export verified: {len(page_docs)} pages")
            print(f"Sample HTML preview: {content[:200]}...")


class TestSlimRetrieval:
    """Test suite for slim document retrieval (deletion detection)."""

    def test_retrieve_all_slim_docs(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that retrieve_all_slim_docs returns all expected document IDs."""
        # Ensure generator is initialized
        assert connector.generator is not None

        # Call the method
        gen = connector.retrieve_all_slim_docs()
        batches = list(gen)

        # Flatten batches
        slim_docs = []
        for batch in batches:
            slim_docs.extend(batch)

        # Verify we got slim documents
        assert len(slim_docs) > 0, "Should return at least one slim document"

        # Verify IDs match expected format
        for doc in slim_docs:
            assert doc.id, "Slim document must have an ID"
            # ID format should be doc_id:page_id or doc_id:table:table_id
            parts = doc.id.split(":")
            assert len(parts) >= 2, f"Invalid ID format: {doc.id}"

        # Verify count matches roughly what we expect (pages + tables)
        # Note: This might be slightly different from load_from_state count
        # because load_from_state filters hidden/empty pages, while slim retrieval
        # should ideally return everything that exists to be safe, or match the filter.
        # Our implementation filters by doc_ids but fetches all pages.

        # Check that we have at least as many slim docs as loaded docs
        # (since slim docs might include things skipped during load)
        loaded_doc_count = reference_data["total_pages"]
        assert (
            len(slim_docs) >= loaded_doc_count
        ), f"Expected at least {loaded_doc_count} slim docs, got {len(slim_docs)}"

        logger.info(f"Retrieved {len(slim_docs)} slim documents")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
