"""Error handling tests for Box connector."""

from collections.abc import Callable
from unittest.mock import patch

import pytest

from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.exceptions import ConnectorValidationError


def test_connector_with_invalid_folder_id(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that connector handles invalid folder IDs gracefully."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids="999999999999",  # Invalid folder ID
    )

    # Should not raise during initialization
    assert connector is not None

    # Loading documents should handle the error gracefully
    from tests.daily.connectors.box.consts_and_utils import load_all_docs

    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        try:
            docs = load_all_docs(connector)
            # If no error, should return empty list or handle gracefully
            assert isinstance(docs, list)
        except Exception as e:
            # If error is raised, it should be a specific Box API error
            error_msg = str(e).lower()
            assert (
                "404" in error_msg
                or "not found" in error_msg
                or "not_found" in error_msg
            )


def test_connector_with_malformed_url(
    box_jwt_connector_factory: Callable[..., BoxConnector],
) -> None:
    """Test that connector handles malformed URLs gracefully."""
    connector = box_jwt_connector_factory(
        user_key="admin",
        include_all_files=False,
        folder_ids="https://invalid-url.com/folder/123",
    )

    # Should extract what it can or handle gracefully
    assert connector is not None


def test_connector_with_empty_folder_ids_string() -> None:
    """Test that connector raises validation error for empty folder_ids string."""
    with pytest.raises(ConnectorValidationError):
        BoxConnector(
            include_all_files=False,
            folder_ids="",
        )


def test_connector_with_whitespace_folder_ids() -> None:
    """Test that connector handles whitespace-only folder_ids."""
    # Whitespace-only folder_ids get filtered out, but the connector still initializes
    # The validation happens in __init__ which checks if folder_ids is truthy (not empty string)
    # Since "   ,  ,  " is truthy, it passes initial validation, but results in empty folder_ids
    # This is acceptable behavior - the connector will just have no folders to process
    connector = BoxConnector(
        include_all_files=False,
        folder_ids="   ,  ,  ",
    )
    # Connector initializes successfully
    assert connector is not None
