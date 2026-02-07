"""Tests for DirectoryConnector."""

import tempfile
import time
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.connectors.directory.connector import DirectoryCheckpoint
from onyx.connectors.directory.connector import DirectoryConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document


# Path to the test data directory.
TEST_DATA_DIR = Path(__file__).parent / "test_data"


def exhaust_connector(
    connector: DirectoryConnector,
    start: float = 0.0,
    end: float | None = None,
) -> tuple[list[Document], list[ConnectorFailure], DirectoryCheckpoint]:
    """Fully exhaust connector and collect all documents and failures."""
    if end is None:
        end = time.time()

    documents: list[Document] = []
    failures: list[ConnectorFailure] = []

    checkpoint = connector.build_dummy_checkpoint()

    while checkpoint.has_more:
        for item in connector.load_from_checkpoint(start, end, checkpoint):
            if isinstance(item, Document):
                documents.append(item)
            elif isinstance(item, ConnectorFailure):
                failures.append(item)
            else:
                # Last item is the checkpoint
                checkpoint = item

    return documents, failures, checkpoint


class TestDirectoryConnector:
    """Test suite for DirectoryConnector."""

    def test_scan_first_level_text_files(self, db_session: Session) -> None:
        """Test scanning only first-level text files in test data directory."""
        connector = DirectoryConnector(
            root_directory=str(TEST_DATA_DIR), recursive=False
        )

        # Scan the directory
        documents, failures, checkpoint = exhaust_connector(connector)

        # Verify no failures
        assert len(failures) == 0, f"Unexpected failures: {failures}"

        # We should get at least the README.md file (only first-level files)
        assert (
            len(documents) >= 1
        ), f"Expected at least 1 document, got {len(documents)}"

        # Verify we got README.md
        doc_ids = {doc.id for doc in documents}
        assert (
            "DIRECTORY_CONNECTOR__README.md" in doc_ids
        ), f"Missing README.md in {doc_ids}"

        # Verify we didn't get files from subdirectories
        for doc_id in doc_ids:
            assert "/" not in doc_id.replace(
                "DIRECTORY_CONNECTOR__", ""
            ), f"Should not have subdirectory file: {doc_id}"

        # Verify all documents have text content
        for doc in documents:
            assert len(doc.sections) > 0, f"Document {doc.id} has no sections"
            assert doc.sections[0].text, f"Document {doc.id} has no text"

        # Verify scan completed
        assert not checkpoint.has_more

    def test_recursive_traversal(self, db_session: Session) -> None:
        """Test recursive traversal finds files in subdirectories."""
        connector = DirectoryConnector(
            root_directory=str(TEST_DATA_DIR), recursive=True
        )

        # Scan the directory
        documents, failures, checkpoint = exhaust_connector(connector)

        # Verify no failures
        assert len(failures) == 0, f"Unexpected failures: {failures}"

        # Should find files in subdirectories
        doc_ids = {doc.id for doc in documents}

        # Should have README.md at top level
        assert "DIRECTORY_CONNECTOR__README.md" in doc_ids

        # Should have files from code/ subdirectory
        assert "DIRECTORY_CONNECTOR__code/example.py" in doc_ids
        assert "DIRECTORY_CONNECTOR__code/example.ts" in doc_ids
        assert "DIRECTORY_CONNECTOR__code/example.js" in doc_ids

        # Should have files from documents/ subdirectory
        assert "DIRECTORY_CONNECTOR__documents/notes.txt" in doc_ids
        assert "DIRECTORY_CONNECTOR__documents/config.json" in doc_ids
        assert "DIRECTORY_CONNECTOR__documents/settings.yaml" in doc_ids

        # Verify we got more files than non-recursive scan
        assert (
            len(documents) >= 7
        ), f"Expected at least 7 documents, got {len(documents)}"

        # Verify scan completed
        assert not checkpoint.has_more

    def test_file_exclusion(self, db_session: Session) -> None:
        """Test excluding files by regex patterns."""
        # Exclude .py files and any file with "config" in the name
        connector = DirectoryConnector(
            root_directory=str(TEST_DATA_DIR),
            recursive=True,
            exclude_patterns=[r"\.py$", r"config"],
        )

        # Scan the directory
        documents, failures, checkpoint = exhaust_connector(connector)

        # Verify no failures
        assert len(failures) == 0, f"Unexpected failures: {failures}"

        doc_ids = {doc.id for doc in documents}

        # Should NOT have .py files
        assert "DIRECTORY_CONNECTOR__code/example.py" not in doc_ids

        # Should NOT have files with "config" in the name
        assert "DIRECTORY_CONNECTOR__documents/config.json" not in doc_ids

        # Should have other files
        assert "DIRECTORY_CONNECTOR__README.md" in doc_ids
        assert "DIRECTORY_CONNECTOR__code/example.ts" in doc_ids
        assert "DIRECTORY_CONNECTOR__code/example.js" in doc_ids
        assert "DIRECTORY_CONNECTOR__documents/notes.txt" in doc_ids
        assert "DIRECTORY_CONNECTOR__documents/settings.yaml" in doc_ids

        # Verify scan completed
        assert not checkpoint.has_more

    def test_unsupported_extensions(self, db_session: Session) -> None:
        """Test that files with unsupported extensions are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with both supported and unsupported extensions
            supported_file = Path(tmpdir) / "supported.txt"
            supported_file.write_text("This is a text file")

            unsupported_file1 = Path(tmpdir) / "unsupported.exe"
            unsupported_file1.write_bytes(b"binary data")

            unsupported_file2 = Path(tmpdir) / "unsupported.mp3"
            unsupported_file2.write_bytes(b"audio data")

            unsupported_file3 = Path(tmpdir) / "unsupported.png"
            unsupported_file3.write_bytes(b"image data")

            # Scan the directory
            connector = DirectoryConnector(root_directory=tmpdir, recursive=False)
            documents, failures, checkpoint = exhaust_connector(connector)

            # Verify no failures
            assert len(failures) == 0, f"Unexpected failures: {failures}"

            # Should only get the supported .txt file
            assert len(documents) == 1, f"Expected 1 document, got {len(documents)}"
            assert documents[0].id == "DIRECTORY_CONNECTOR__supported.txt"

            # Verify scan completed
            assert not checkpoint.has_more
