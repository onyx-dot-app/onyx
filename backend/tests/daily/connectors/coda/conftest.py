"""
Shared pytest fixtures for Coda connector integration tests.

This conftest.py file provides common fixtures used across all test files,
reducing duplication and improving maintainability.

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Set CODA_FOLDER_ID environment variable
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


# ============================================================================
# Environment & Authentication Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def api_token() -> str:
    """Fixture to get and validate API token."""
    token = os.environ.get("CODA_API_TOKEN")
    if not token:
        pytest.skip("CODA_API_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def coda_folder_id() -> str:
    """Fixture to get docs from a specific folder."""
    folder_id = os.environ.get("CODA_FOLDER_ID")
    if not folder_id:
        pytest.skip("CODA_FOLDER_ID not set")
    return folder_id


@pytest.fixture(scope="session")
def api_client(api_token: str) -> CodaAPIClient:
    """Fixture to create and authenticate API client."""
    client = CodaAPIClient(api_token)
    client.validate_credentials()
    return client


# ============================================================================
# Document Creation Fixtures
# ============================================================================


def _wait_for_doc_availability(
    client: CodaAPIClient, doc_id: str, timeout: int = 60, check_pages: bool = False
) -> bool:
    """Helper to poll for doc availability."""
    logger.info(f"[SETUP] Polling for doc {doc_id} availability...")
    start_time = time()

    while time() - start_time < timeout:
        try:
            check_response = client._make_request("GET", f"/docs/{doc_id}")
            if check_pages:
                client._make_request("GET", f"/docs/{doc_id}/pages")

            if check_response and check_response.get("id") == doc_id:
                elapsed = time() - start_time
                logger.info(f"[SETUP] Doc {doc_id} available after {elapsed:.1f}s")
                return True
        except Exception:
            pass
        sleep(2)

    logger.warning(f"[SETUP] Doc {doc_id} not available after {timeout}s")
    return False


def _delete_doc_with_retry(
    client: CodaAPIClient, doc_id: str, max_attempts: int = 5, retry_delay: int = 2
) -> bool:
    """Helper to delete a doc with retries."""
    for attempt in range(1, max_attempts + 1):
        try:
            client._make_request("DELETE", f"/docs/{doc_id}")
            logger.info(f"[TEARDOWN] Successfully deleted doc: {doc_id}")
            return True
        except Exception as e:
            if attempt < max_attempts:
                logger.warning(
                    f"[TEARDOWN] Delete attempt {attempt}/{max_attempts} failed for {doc_id}: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                sleep(retry_delay)
            else:
                logger.error(
                    f"[TEARDOWN] Failed to delete doc {doc_id} after {max_attempts} attempts: {e}"
                )
                return False
    return False


@pytest.fixture(scope="session")
def template_test_doc(
    api_token: str, coda_folder_id: str
) -> Generator[dict[str, Any], None, None]:
    """
    Creates a test doc from template (for comprehensive tests).
    Session-scoped for maximum reuse across all tests.
    """
    client = CodaAPIClient(api_token)

    response = client.create_doc(
        title="Two-way writeups: Coda's secret to shipping fast",
        source_doc="_WhgwP-IEe",
        folder_id=coda_folder_id,
    )

    logger.info(
        f"[SETUP] Created template doc: {response['name']} (ID: {response['id']})"
    )

    _wait_for_doc_availability(client, response["id"])

    yield response

    # Cleanup
    _delete_doc_with_retry(client, response["id"])


@pytest.fixture(scope="session")
def simple_test_doc(
    api_token: str, coda_folder_id: str
) -> Generator[dict[str, Any], None, None]:
    """
    Creates a simple test doc with minimal content (for basic tests).
    Session-scoped for maximum reuse.
    """
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

    logger.info(
        f"[SETUP] Created simple doc: {response['name']} (ID: {response['id']})"
    )

    _wait_for_doc_availability(client, response["id"], check_pages=True)

    yield response

    # Cleanup
    _delete_doc_with_retry(client, response["id"])


# ============================================================================
# Connector Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def template_connector(
    api_token: str, template_test_doc: dict[str, Any]
) -> CodaConnector:
    """Connector configured for template test doc."""
    conn = CodaConnector(
        batch_size=5,
        doc_ids=[template_test_doc["id"]],
    )
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


@pytest.fixture(scope="module")
def simple_connector(api_token: str, simple_test_doc: dict[str, Any]) -> CodaConnector:
    """Connector configured for simple test doc."""
    conn = CodaConnector(
        batch_size=5,
        doc_ids=[simple_test_doc["id"]],
    )
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


# ============================================================================
# Data Loading Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def all_batches(template_connector: CodaConnector) -> list[list[Document]]:
    """
    Loads all batches once and caches them for the module.
    Significantly reduces API calls by avoiding repeated load_from_state() calls.
    """
    assert template_connector.generator is not None
    template_connector.generator.indexed_pages.clear()
    template_connector.generator.indexed_tables.clear()

    logger.info("Loading all batches...")
    gen = template_connector.load_from_state()
    batches = list(gen)
    logger.info(f"Loaded {len(batches)} batches")
    return batches


@pytest.fixture(scope="module")
def reference_data(
    api_client: CodaAPIClient,
    template_connector: CodaConnector,
    template_test_doc: dict[str, Any],
    all_batches: list[list[Document]],
) -> dict[str, Any]:
    """
    Fetches reference data from API for validation.
    Depends on all_batches to ensure it runs after data is loaded.
    """
    all_docs = template_connector.doc_ids

    if not all_docs:
        pytest.skip("No docs found in Coda workspace")

    expected_page_count = 0
    expected_pages_by_doc = {}

    for doc_id in all_docs:
        pages = api_client.fetch_all_pages(doc_id)
        non_hidden_pages = [
            p
            for p in pages
            if not p.isHidden and p.id not in template_connector.generator.skipped_pages
        ]
        expected_pages_by_doc[doc_id] = non_hidden_pages
        expected_page_count += len(non_hidden_pages)

    if expected_page_count == 0:
        pytest.skip("No visible pages found in Coda workspace")

    return {
        "docs": all_docs,
        "total_pages": expected_page_count,
        "pages_by_doc": expected_pages_by_doc,
    }


@pytest.fixture(scope="module")
def all_documents(all_batches: list[list[Document]]) -> list[Document]:
    """Flattens all batches into a single list of documents."""
    return [doc for batch in all_batches for doc in batch]


@pytest.fixture(scope="module")
def simple_all_batches(simple_connector: CodaConnector) -> list[list[Document]]:
    """
    Loads all batches once and caches them for the module.
    Significantly reduces API calls by avoiding repeated load_from_state() calls.
    """
    assert simple_connector.generator is not None
    simple_connector.generator.indexed_pages.clear()
    simple_connector.generator.indexed_tables.clear()

    logger.info("Loading all batches...")
    gen = simple_connector.load_from_state()
    batches = list(gen)
    logger.info(f"Loaded {len(batches)} batches")
    return batches


@pytest.fixture(scope="module")
def simple_reference_data(
    api_client: CodaAPIClient,
    simple_connector: CodaConnector,
    simple_test_doc: dict[str, Any],
    simple_all_batches: list[list[Document]],
) -> dict[str, Any]:
    """
    Fetches reference data from API for validation.
    Depends on all_batches to ensure it runs after data is loaded.
    """
    all_docs = simple_connector.doc_ids

    if not all_docs:
        pytest.skip("No docs found in Coda workspace")

    expected_page_count = 0
    expected_pages_by_doc = {}

    for doc_id in all_docs:
        pages = api_client.fetch_all_pages(doc_id)
        non_hidden_pages = [
            p
            for p in pages
            if not p.isHidden and p.id not in simple_connector.generator.skipped_pages
        ]
        expected_pages_by_doc[doc_id] = non_hidden_pages
        expected_page_count += len(non_hidden_pages)

    if expected_page_count == 0:
        pytest.skip("No visible pages found in Coda workspace")

    return {
        "docs": all_docs,
        "total_pages": expected_page_count,
        "pages_by_doc": expected_pages_by_doc,
    }
