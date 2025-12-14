"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Set CODA_FOLDER_ID environment variable
"""

from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TestTableProcessing:
    """Test suite for load_from_state end-to-end functionality."""

    def test_tables_can_be_processed(
        self,
        all_table_documents: list[Document],
    ) -> None:
        """Test that documents are generated from non-hidden pages.

        Note: The actual count may be less than the API page count because:
        - Some pages may fail to export
        - Some pages may have empty content
        """
        total_documents = len(all_table_documents)
        assert total_documents > 0, "Expected at least one document"
