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
def test_doc(
    api_token: str, coda_folder_id: str
) -> Generator[dict[str, Any], None, None]:
    """Fixture that creates a test doc once for the entire test session.

    Creates a doc by copying from a template, yields it for tests,
    and cleans it up after all tests complete.
    """
    logger.info(f"[SETUP] Creating test doc... {api_token}")
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

    logger.info("[SETUP] Polling for doc availability...")
    start_time = time()
    timeout = 60
    doc_available = False

    while time() - start_time < timeout:
        try:
            check_response = client._make_request("GET", f"/docs/{response['id']}")
            if check_response and check_response.get("id") == response["id"]:
                logger.info(f"[SETUP] Doc available after {time() - start_time:.1f}s")
                doc_available = True
                break
        except Exception:
            pass
        sleep(2)

    if not doc_available:
        logger.warning(
            f"[SETUP] Warning: Doc not available after {timeout}s, tests may fail"
        )

    yield response
    # try:
    #     client._make_request("DELETE", f"/docs/{response['id']}")
    #     logger.info(f"[TEARDOWN] Deleted test doc: {response['id']}")
    # except Exception as e:
    #     logger.warning(
    #         f"[TEARDOWN] Warning: Failed to delete test doc {response['id']}: {e}"
    #     )


@pytest.fixture(scope="module")
def connector(api_token: str, test_doc: dict[str, Any]) -> CodaConnector:
    """Fixture for a connector configured for polling."""
    conn = CodaConnector(
        batch_size=5,
        doc_ids=[test_doc["id"]],
    )
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


class TestPollSource:
    """Test suite for poll_source functionality."""

    def test_poll_source_returns_updated_docs(
        self,
        connector: CodaConnector,
        api_client: CodaAPIClient,
        test_doc: dict[str, Any],
    ) -> None:
        """Test that poll_source returns documents updated within the window."""
        doc_id = test_doc["id"]

        page_name = f"Polling Test Page {time()}"
        page_res = api_client.create_page(
            doc_id=doc_id, name=page_name, content_html="<p>Initial content</p>"
        )
        page_id = page_res["id"]

        logger.info(f"Created polling to update test page: {page_name} ({page_id})")

        start_time = time()
        timeout = 60

        while time() - start_time < timeout:
            try:
                # Update the page
                logger.info(f"Trying to update page: {page_name} ({page_id})")
                api_client.update_page(
                    doc_id=doc_id,
                    page_id=page_id,
                    content_html="<p>Updated content for polling test</p>",
                )
                logger.info("Updated page")
                break

            except Exception:
                sleep(2)

        sleep(20)
        end_time = time()

        logger.info(f"Polling between {start_time} and {end_time}")
        gen = connector.poll_source(start_time, end_time)
        batches = list(gen)

        logger.info(f"Received {len(batches)} batches")
        logger.info(batches)

        # Verify
        found_page = False
        for batch in batches:
            for doc in batch:
                if doc.metadata.get("page_id") == page_id:
                    found_page = True
                    assert "Updated content" in doc.sections[0].text
                    logger.info("Found updated page in poll results")

        assert found_page, "Updated page should be returned by poll_source"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
