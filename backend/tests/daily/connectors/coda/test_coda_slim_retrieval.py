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

from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()


@pytest.fixture(scope="module")
def api_token() -> str:
    """Fixture to get and validate API token."""
    token = os.environ.get("CODA_API_TOKEN")
    if not token:
        pytest.skip("CODA_API_TOKEN not set")
    return token


@pytest.fixture(scope="module")
def coda_folder_id() -> str:
    """Fixture to get docs from a specific folder."""
    token = os.environ.get("CODA_FOLDER_ID")
    if not token:
        pytest.skip("CODA_FOLDER_ID not set")
    return token


@pytest.fixture(scope="module")
def api_client(api_token: str) -> CodaAPIClient:
    """Fixture to create and authenticate API client."""
    client = CodaAPIClient(api_token)
    client.validate_credentials()
    return client


@pytest.fixture(scope="module")
def connector(
    request: pytest.FixtureRequest, api_token: str, test_doc: dict[str, Any]
) -> CodaConnector:
    """Fixture to create and authenticate connector."""
    conn = CodaConnector(
        batch_size=5,
        doc_ids=[test_doc["id"]],
    )
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


@pytest.fixture(scope="module")
def reference_data(
    api_client: CodaAPIClient,
    connector: CodaConnector,
    test_doc: dict[str, Any],
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


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def test_doc(
    api_token: str, coda_folder_id: str
) -> Generator[dict[str, Any], None, None]:
    """Fixture that creates a test doc once for the entire test session.

    Creates a doc by copying from a template, yields it for tests,
    and cleans it up after all tests complete.
    """
    # Create a temporary API client for setup/teardown
    client = CodaAPIClient(api_token)

    response = client.create_doc(
        title="Simple Document",
        folder_id=coda_folder_id,
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

    logger.info(f"[SETUP] Created test doc: {response['name']}")
    logger.info(f"[SETUP] Doc ID: {response['id']}")
    logger.info(f"[SETUP] Browser link: {response['browserLink']}")

    # Poll for doc availability instead of hard sleep
    logger.info("[SETUP] Polling for doc availability...")
    start_time = time()
    timeout = 60
    doc_available = False

    while time() - start_time < timeout:
        try:
            # Try to fetch the doc
            check_response = client._make_request("GET", f"/docs/{response['id']}")
            client._make_request("GET", f"/docs/{response['id']}/pages")
            if check_response and check_response.get("id") == response["id"]:
                logger.info(
                    f"[SETUP] Doc {response['id']} available after {time() - start_time:.1f}s"
                )
                doc_available = True
                break
        except Exception:
            pass
        sleep(5)

    if not doc_available:
        logger.warning(
            f"[SETUP] Warning: Doc not available after {timeout}s, tests may fail"
        )

    # Yield the doc info for tests to use
    yield response

    # Cleanup: Delete the doc after all tests complete
    try:
        client._make_request("DELETE", f"/docs/{response['id']}")
        logger.info(f"[TEARDOWN] Deleted test doc: {response['id']}")
    except Exception as e:
        logger.warning(
            f"[TEARDOWN] Warning: Failed to delete test doc {response['id']}: {e}"
        )


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

        loaded_doc_count = reference_data["total_pages"]
        assert (
            len(slim_docs) >= loaded_doc_count
        ), f"Expected at least {loaded_doc_count} slim docs, got {len(slim_docs)}"

        logger.info(f"Retrieved {len(slim_docs)} slim documents")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
