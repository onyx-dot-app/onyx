"""
Unit tests for lazy loading connector factory to validate:
1. All connector mappings are correct
2. Module paths and class names are valid
3. Error handling works properly
4. Caching functions correctly
"""

import importlib
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import _connector_cache
from onyx.connectors.factory import _load_connector_class
from onyx.connectors.factory import ConnectorMissingException
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.registry import ConnectorMapping


class TestConnectorMappingValidation:
    """Test that all connector mappings are valid."""

    def test_all_connector_mappings_exist(self) -> None:
        """Test that all mapped modules and classes actually exist."""
        errors = []

        for source, mapping in CONNECTOR_CLASS_MAP.items():
            try:
                # Try to import the module
                module = importlib.import_module(mapping.module_path)

                # Try to get the class
                connector_class = getattr(module, mapping.class_name)

                # Verify it's a subclass of BaseConnector
                if not issubclass(connector_class, BaseConnector):
                    errors.append(
                        f"{source.value}: {mapping.class_name} is not a BaseConnector subclass"
                    )

            except ImportError as e:
                errors.append(
                    f"{source.value}: Failed to import {mapping.module_path} - {e}"
                )
            except AttributeError as e:
                errors.append(
                    f"{source.value}: Class {mapping.class_name} not found in {mapping.module_path} - {e}"
                )

        if errors:
            pytest.fail("Connector mapping validation failed:\n" + "\n".join(errors))

    def test_no_duplicate_mappings(self) -> None:
        """Test that each DocumentSource only appears once in the mapping."""
        sources = list(CONNECTOR_CLASS_MAP.keys())
        unique_sources = set(sources)

        assert len(sources) == len(
            unique_sources
        ), "Duplicate DocumentSource entries found"

    def test_blob_storage_connectors_correct(self) -> None:
        """Test that all blob storage sources map to the same connector."""
        blob_sources = [
            DocumentSource.S3,
            DocumentSource.R2,
            DocumentSource.GOOGLE_CLOUD_STORAGE,
            DocumentSource.OCI_STORAGE,
        ]

        expected_mapping = ConnectorMapping(
            module_path="onyx.connectors.blob.connector",
            class_name="BlobStorageConnector",
        )

        for source in blob_sources:
            assert (
                CONNECTOR_CLASS_MAP[source] == expected_mapping
            ), f"{source.value} should map to BlobStorageConnector"


class TestConnectorClassLoading:
    """Test the lazy loading mechanism."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _connector_cache.clear()

    def test_load_connector_class_success(self) -> None:
        """Test successful connector class loading."""
        # Use a simple connector that should always exist
        connector_class = _load_connector_class(DocumentSource.WEB)

        assert connector_class is not None
        assert issubclass(connector_class, BaseConnector)
        assert connector_class.__name__ == "WebConnector"

    def test_load_connector_class_caching(self) -> None:
        """Test that connector classes are cached after first load."""
        assert len(_connector_cache) == 0

        # Load connector first time
        connector_class1 = _load_connector_class(DocumentSource.WEB)
        assert len(_connector_cache) == 1
        assert DocumentSource.WEB in _connector_cache

        # Load same connector second time - should use cache
        connector_class2 = _load_connector_class(DocumentSource.WEB)
        assert connector_class1 is connector_class2  # Same object reference
        assert len(_connector_cache) == 1  # Cache size unchanged

    @patch("importlib.import_module")
    def test_load_connector_class_import_error(self, mock_import: Mock) -> None:
        """Test handling of import errors."""
        mock_import.side_effect = ImportError("Module not found")

        with pytest.raises(ConnectorMissingException) as exc_info:
            _load_connector_class(DocumentSource.WEB)

        assert (
            "Failed to import WebConnector from onyx.connectors.web.connector"
            in str(exc_info.value)
        )

    @patch("importlib.import_module")
    def test_load_connector_class_attribute_error(self, mock_import: Mock) -> None:
        """Test handling of missing class in module."""

        # Create a custom mock that raises AttributeError for the specific class
        class MockModule:
            def __getattr__(self, name: str) -> MagicMock:
                if name == "WebConnector":
                    raise AttributeError("Class not found")
                return MagicMock()

        mock_import.return_value = MockModule()

        with pytest.raises(ConnectorMissingException) as exc_info:
            _load_connector_class(DocumentSource.WEB)

        assert (
            "Failed to import WebConnector from onyx.connectors.web.connector"
            in str(exc_info.value)
        )


class TestIdentifyConnectorClass:
    """Test the identify_connector_class function."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _connector_cache.clear()

    def test_identify_connector_basic(self) -> None:
        """Test basic connector identification."""
        connector_class = identify_connector_class(
            DocumentSource.GITHUB, InputType.SLIM_RETRIEVAL
        )

        assert connector_class is not None
        assert issubclass(connector_class, BaseConnector)
        assert connector_class.__name__ == "GithubConnector"

    def test_identify_connector_slack_special_case(self) -> None:
        """Test Slack connector special handling."""
        # Test POLL input type
        slack_poll = identify_connector_class(DocumentSource.SLACK, InputType.POLL)
        assert slack_poll.__name__ == "SlackConnector"

        # Test SLIM_RETRIEVAL input type
        slack_slim = identify_connector_class(
            DocumentSource.SLACK, InputType.SLIM_RETRIEVAL
        )
        assert slack_slim.__name__ == "SlackConnector"

        # Should be the same class
        assert slack_poll is slack_slim

    def test_identify_connector_without_input_type(self) -> None:
        """Test connector identification without specifying input type."""
        connector_class = identify_connector_class(DocumentSource.GITHUB)

        assert connector_class is not None
        assert connector_class.__name__ == "GithubConnector"


class TestConnectorMappingIntegrity:
    """Test integrity of the connector mapping data."""

    def test_all_document_sources_mapped(self) -> None:
        """Test that all DocumentSource values have mappings (where expected)."""
        # Get all DocumentSource enum values
        all_sources = set(DocumentSource)
        mapped_sources = set(CONNECTOR_CLASS_MAP.keys())

        expected_unmapped = {
            DocumentSource.INGESTION_API,  # This is handled differently
            DocumentSource.REQUESTTRACKER,  # Not yet implemented or special case
            DocumentSource.NOT_APPLICABLE,  # Special placeholder, no connector needed
            DocumentSource.USER_FILE,  # Special placeholder, no connector needed
            # Add other legitimately unmapped sources here if they exist
        }

        unmapped_sources = all_sources - mapped_sources - expected_unmapped

        if unmapped_sources:
            pytest.fail(
                f"DocumentSource values without connector mappings: "
                f"{[s.value for s in unmapped_sources]}"
            )

    def test_mapping_format_consistency(self) -> None:
        """Test that all mappings follow the expected format."""
        for source, mapping in CONNECTOR_CLASS_MAP.items():
            assert isinstance(
                mapping, ConnectorMapping
            ), f"{source.value} mapping is not a ConnectorMapping"

            assert isinstance(
                mapping.module_path, str
            ), f"{source.value} module_path is not a string"
            assert isinstance(
                mapping.class_name, str
            ), f"{source.value} class_name is not a string"
            assert mapping.module_path.startswith(
                "onyx.connectors."
            ), f"{source.value} module_path doesn't start with onyx.connectors."
            assert mapping.class_name.endswith(
                "Connector"
            ), f"{source.value} class_name doesn't end with Connector"


class TestInstantiateConnectorIntegration:
    """Test that the lazy loading works with the main instantiate_connector function."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _connector_cache.clear()

    def test_instantiate_connector_loads_class_lazily(self) -> None:
        """Test that instantiate_connector triggers lazy loading."""
        # Mock the database session and credential
        mock_session = MagicMock()
        mock_credential = MagicMock()
        mock_credential.id = 123
        mock_credential.credential_json = {"test": "data"}

        # This should trigger lazy loading but will fail on actual instantiation
        # due to missing real configuration - that's expected
        with pytest.raises(Exception):  # We expect some kind of error due to mock data
            instantiate_connector(
                mock_session,
                DocumentSource.WEB,  # Simple connector
                InputType.SLIM_RETRIEVAL,
                {},  # Empty config
                mock_credential,
            )

        # But the class should have been loaded into cache
        assert DocumentSource.WEB in _connector_cache
        assert _connector_cache[DocumentSource.WEB].__name__ == "WebConnector"
