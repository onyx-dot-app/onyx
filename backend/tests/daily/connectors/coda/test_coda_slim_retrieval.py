"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Set CODA_FOLDER_ID environment variable
"""

from typing import Any

import pytest

from onyx.connectors.coda.connector import CodaConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TestSlimRetrieval:
    """Test suite for slim document retrieval (deletion detection)."""

    def test_retrieve_all_slim_docs(
        self, simple_connector: CodaConnector, simple_reference_data: dict[str, Any]
    ) -> None:
        """Test that retrieve_all_slim_docs returns all expected document IDs."""
        # Ensure generator is initialized
        assert simple_connector.generator is not None

        # Call the method
        gen = simple_connector.retrieve_all_slim_docs()
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

        loaded_doc_count = simple_reference_data["total_pages"]
        assert (
            len(slim_docs) >= loaded_doc_count
        ), f"Expected at least {loaded_doc_count} slim docs, got {len(slim_docs)}"

        logger.info(f"Retrieved {len(slim_docs)} slim documents")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
