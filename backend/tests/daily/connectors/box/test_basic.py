"""Basic tests for Box connector."""

import time
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.box.connector import BoxConnector
from tests.daily.connectors.box.consts_and_utils import ADMIN_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import ADMIN_FOLDER_3_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import (
    assert_expected_docs_in_retrieved_docs,
)
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_ID
from tests.daily.connectors.box.consts_and_utils import FOLDER_1_URL
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_ID
from tests.daily.connectors.box.consts_and_utils import FOLDER_2_URL
from tests.daily.connectors.box.consts_and_utils import FOLDER_3_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import load_all_docs
from tests.daily.connectors.box.consts_and_utils import SECTIONS_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import TEST_USER_1_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import TEST_USER_2_FILE_IDS
from tests.daily.connectors.box.consts_and_utils import TEST_USER_3_FILE_IDS


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_include_all_files(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that include_all_files=True indexes everything from root."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get everything accessible from root (test parent folder)
    expected_file_ids = (
        ADMIN_FILE_IDS
        + ADMIN_FOLDER_3_FILE_IDS
        + TEST_USER_1_FILE_IDS
        + TEST_USER_2_FILE_IDS
        + TEST_USER_3_FILE_IDS
        + FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
        + FOLDER_3_FILE_IDS  # Folder 3 is in the test structure
        + SECTIONS_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_specific_folders(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that folder_ids with specific folder IDs works."""
    folder_ids = f"{FOLDER_1_ID},{FOLDER_2_ID}"
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=folder_ids,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get files from folder 1 and folder 2 (including subfolders)
    expected_file_ids = (
        FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_folder_urls(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that folder_ids with Box URLs extracts IDs correctly."""
    folder_urls = f"{FOLDER_1_URL},{FOLDER_2_URL}"
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=folder_urls,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get files from folder 1 and folder 2 (including subfolders)
    expected_file_ids = (
        FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_mixed_folder_ids_and_urls(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test combination of folder IDs and URLs."""
    mixed_ids = f"{FOLDER_1_ID},{FOLDER_2_URL}"
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=mixed_ids,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get files from both folders
    expected_file_ids = (
        FOLDER_1_FILE_IDS
        + FOLDER_1_1_FILE_IDS
        + FOLDER_1_2_FILE_IDS
        + FOLDER_2_FILE_IDS
        + FOLDER_2_1_FILE_IDS
        + FOLDER_2_2_FILE_IDS
    )
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_single_folder(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test indexing a single folder."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=FOLDER_1_ID,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get files from folder 1 and its subfolders
    expected_file_ids = FOLDER_1_FILE_IDS + FOLDER_1_1_FILE_IDS + FOLDER_1_2_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_nested_folders(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test recursive folder traversal with deeply nested structure."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=FOLDER_2_ID,
    )
    retrieved_docs = load_all_docs(connector)

    # Should get files from folder 2 and all nested subfolders (2-1 and 2-2)
    expected_file_ids = FOLDER_2_FILE_IDS + FOLDER_2_1_FILE_IDS + FOLDER_2_2_FILE_IDS
    assert_expected_docs_in_retrieved_docs(
        retrieved_docs=retrieved_docs,
        expected_file_ids=expected_file_ids,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_size_threshold(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """
    Test that size_threshold is applied correctly.

    Since all test files are small (< 1KB), this verifies the threshold
    doesn't block all files rather than testing exclusion of large files.
    """
    from tests.daily.connectors.box.consts_and_utils import FOLDER_1_URL

    # Test with a reasonable size threshold (16KB) - test files are small text files
    connector_with_threshold = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids=FOLDER_1_URL,
    )
    connector_with_threshold.size_threshold = 16384  # 16KB

    retrieved_docs = load_all_docs(connector_with_threshold)
    threshold_doc_names = {doc.semantic_identifier for doc in retrieved_docs}

    # With a 16KB threshold, all small test files should still be retrieved
    # (test files are small text files, typically < 1KB each)
    assert (
        len(retrieved_docs) > 0
    ), "Should retrieve at least some files with 16KB threshold"

    # Verify that files were retrieved (threshold didn't block all files)
    # Since test files are small, they should all pass the 16KB threshold
    assert len(threshold_doc_names) > 0, (
        f"With 16KB threshold, should retrieve files from {FOLDER_1_URL}. "
        f"Got {len(retrieved_docs)} documents."
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_checkpoint_resumption(
    mock_get_api_key: MagicMock,
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test checkpointing and resuming from checkpoint."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )

    # Create initial checkpoint
    checkpoint = connector.build_dummy_checkpoint()
    assert checkpoint is not None
    assert checkpoint.has_more is True

    # Load some documents
    from onyx.connectors.connector_runner import CheckpointOutputWrapper

    start_time = 0
    end_time = time.time()

    # Load first batch and get updated checkpoint
    first_checkpoint_file_count = len(checkpoint.all_retrieved_file_ids)
    doc_batch_generator = CheckpointOutputWrapper[BoxConnector]()(
        connector.load_from_checkpoint(start_time, end_time, checkpoint)
    )
    first_batch_docs = []
    for document, failure, next_checkpoint in doc_batch_generator:
        if failure is not None:
            raise RuntimeError(f"Failed to load documents: {failure}")
        if document is not None:
            first_batch_docs.append(document)
        if next_checkpoint is not None:
            checkpoint = next_checkpoint

    # Load a few more batches to verify checkpointing works
    all_docs = first_batch_docs.copy()
    max_iterations = 2  # Test a few batches to verify checkpointing
    iteration_count = 0
    # Track checkpoint size at start of each iteration to verify growth
    previous_checkpoint_file_count = len(checkpoint.all_retrieved_file_ids)
    while checkpoint.has_more and iteration_count < max_iterations:
        iteration_count += 1

        doc_batch_generator = CheckpointOutputWrapper[BoxConnector]()(
            connector.load_from_checkpoint(start_time, end_time, checkpoint)
        )
        batch_docs = []
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                raise RuntimeError(f"Failed to load documents: {failure}")
            if document is not None:
                batch_docs.append(document)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        all_docs.extend(batch_docs)
        if checkpoint.has_more:
            # Checkpoint should be updated with more file IDs after this batch
            current_checkpoint_file_count = len(checkpoint.all_retrieved_file_ids)
            assert current_checkpoint_file_count > previous_checkpoint_file_count, (
                f"Checkpoint should grow after batch {iteration_count}: "
                f"was {previous_checkpoint_file_count}, now {current_checkpoint_file_count}"
            )
            # Update baseline for next iteration
            previous_checkpoint_file_count = current_checkpoint_file_count

    # Verify we got documents and checkpointing is working
    assert len(all_docs) > 0, "Should have retrieved at least some documents"
    assert (
        len(checkpoint.all_retrieved_file_ids) > first_checkpoint_file_count
    ), "Checkpoint should be updated with retrieved file IDs"


def test_connector_validation(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test validate_connector_settings()."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=True,
        folder_ids=None,
    )

    # Should not raise an exception
    connector.validate_connector_settings()


def test_connector_initialization() -> None:
    """Test that Box connector can be initialized."""
    connector = BoxConnector(
        include_all_files=True,
        folder_ids=None,
    )
    assert connector is not None
    assert connector.include_all_files is True
    assert connector._requested_folder_ids == set()


def test_connector_initialization_with_folder_ids() -> None:
    """Test that Box connector can be initialized with folder IDs."""
    folder_ids = "123,456"
    connector = BoxConnector(
        include_all_files=False,
        folder_ids=folder_ids,
    )
    assert connector is not None
    assert connector.include_all_files is False
    assert "123" in connector._requested_folder_ids
    assert "456" in connector._requested_folder_ids


def test_connector_initialization_fails_without_config() -> None:
    """Test that Box connector fails to initialize without include_all_files or folder_ids."""
    from onyx.connectors.exceptions import ConnectorValidationError

    with pytest.raises(ConnectorValidationError):
        BoxConnector(
            include_all_files=False,
            folder_ids=None,
        )
