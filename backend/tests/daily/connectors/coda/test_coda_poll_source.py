"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Set CODA_FOLDER_ID environment variable
"""

from time import sleep
from time import time
from typing import Any

import pytest

from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.connector import CodaConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TestPollSource:
    """Test suite for poll_source functionality."""

    def test_poll_source_returns_updated_docs(
        self,
        simple_connector: CodaConnector,
        api_client: CodaAPIClient,
        simple_test_doc: dict[str, Any],
    ) -> None:
        """Test that poll_source returns documents updated within the window."""
        doc_id = simple_test_doc["id"]

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
        gen = simple_connector.poll_source(start_time, end_time)
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
