"""
Unit tests for federated connector lazy loading factory to validate:
1. All federated connector mappings are correct
2. Module paths and class names are valid
3. Error handling works properly
4. Caching functions correctly
"""

import importlib
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import FederatedConnectorSource
from onyx.federated_connectors.factory import _federated_connector_cache
from onyx.federated_connectors.factory import _load_federated_connector_class
from onyx.federated_connectors.factory import FederatedConnectorMissingException
from onyx.federated_connectors.factory import get_federated_connector_cls
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.federated_connectors.registry import FEDERATED_CONNECTOR_CLASS_MAP
from onyx.federated_connectors.registry import FederatedConnectorMapping


class TestFederatedConnectorMappingValidation:
    """Test that all federated connector mappings are valid."""

    def test_all_federated_connector_mappings_exist(self) -> None:
        """Test that all mapped modules and classes actually exist."""
        errors = []

        for source, mapping in FEDERATED_CONNECTOR_CLASS_MAP.items():
            try:
                # Try to import the module
                module = importlib.import_module(mapping.module_path)

                # Try to get the class
                connector_class = getattr(module, mapping.class_name)

                # Verify it's a subclass of FederatedConnector
                if not issubclass(connector_class, FederatedConnector):
                    errors.append(
                        f"{source.value}: {mapping.class_name} is not a FederatedConnector subclass"
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
            pytest.fail(
                "Federated connector mapping validation failed:\n" + "\n".join(errors)
            )

    def test_no_duplicate_mappings(self) -> None:
        """Test that each FederatedConnectorSource only appears once in the mapping."""
        sources = list(FEDERATED_CONNECTOR_CLASS_MAP.keys())
        unique_sources = set(sources)

        assert len(sources) == len(
            unique_sources
        ), "Duplicate FederatedConnectorSource entries found"

    def test_mapping_format_consistency(self) -> None:
        """Test that all mappings follow the expected format."""
        for source, mapping in FEDERATED_CONNECTOR_CLASS_MAP.items():
            assert isinstance(
                mapping, FederatedConnectorMapping
            ), f"{source.value} mapping is not a FederatedConnectorMapping"

            assert isinstance(
                mapping.module_path, str
            ), f"{source.value} module_path is not a string"
            assert isinstance(
                mapping.class_name, str
            ), f"{source.value} class_name is not a string"
            assert mapping.module_path.startswith(
                "onyx.federated_connectors."
            ), f"{source.value} module_path doesn't start with onyx.federated_connectors."
            assert mapping.class_name.endswith(
                "FederatedConnector"
            ), f"{source.value} class_name doesn't end with FederatedConnector"


class TestFederatedConnectorClassLoading:
    """Test the lazy loading mechanism."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _federated_connector_cache.clear()

    def test_load_federated_connector_class_success(self) -> None:
        """Test successful federated connector class loading."""
        connector_class = _load_federated_connector_class(
            FederatedConnectorSource.FEDERATED_SLACK
        )

        assert connector_class is not None
        assert issubclass(connector_class, FederatedConnector)
        assert connector_class.__name__ == "SlackFederatedConnector"

    def test_load_federated_connector_class_caching(self) -> None:
        """Test that federated connector classes are cached after first load."""
        assert len(_federated_connector_cache) == 0

        # Load connector first time
        connector_class1 = _load_federated_connector_class(
            FederatedConnectorSource.FEDERATED_SLACK
        )
        assert len(_federated_connector_cache) == 1
        assert FederatedConnectorSource.FEDERATED_SLACK in _federated_connector_cache

        # Load same connector second time - should use cache
        connector_class2 = _load_federated_connector_class(
            FederatedConnectorSource.FEDERATED_SLACK
        )
        assert connector_class1 is connector_class2  # Same object reference
        assert len(_federated_connector_cache) == 1  # Cache size unchanged

    @patch("importlib.import_module")
    def test_load_federated_connector_class_import_error(
        self, mock_import: Mock
    ) -> None:
        """Test handling of import errors."""
        mock_import.side_effect = ImportError("Module not found")

        with pytest.raises(FederatedConnectorMissingException) as exc_info:
            _load_federated_connector_class(FederatedConnectorSource.FEDERATED_SLACK)

        assert (
            "Failed to import SlackFederatedConnector from onyx.federated_connectors.slack.federated_connector"
            in str(exc_info.value)
        )

    @patch("importlib.import_module")
    def test_load_federated_connector_class_attribute_error(
        self, mock_import: Mock
    ) -> None:
        """Test handling of missing class in module."""

        # Create a custom mock that raises AttributeError for the specific class
        class MockModule:
            def __getattr__(self, name: str) -> MagicMock:
                if name == "SlackFederatedConnector":
                    raise AttributeError("Class not found")
                return MagicMock()

        mock_import.return_value = MockModule()

        with pytest.raises(FederatedConnectorMissingException) as exc_info:
            _load_federated_connector_class(FederatedConnectorSource.FEDERATED_SLACK)

        assert (
            "Failed to import SlackFederatedConnector from onyx.federated_connectors.slack.federated_connector"
            in str(exc_info.value)
        )


class TestGetFederatedConnectorCls:
    """Test the get_federated_connector_cls function."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        _federated_connector_cache.clear()

    def test_get_federated_connector_cls_basic(self) -> None:
        """Test basic federated connector class retrieval."""
        connector_class = get_federated_connector_cls(
            FederatedConnectorSource.FEDERATED_SLACK
        )

        assert connector_class is not None
        assert issubclass(connector_class, FederatedConnector)
        assert connector_class.__name__ == "SlackFederatedConnector"


class TestFederatedConnectorMappingIntegrity:
    """Test integrity of the federated connector mapping data."""

    def test_all_federated_connector_sources_mapped(self) -> None:
        """Test that all FederatedConnectorSource values have mappings."""
        # Get all FederatedConnectorSource enum values
        all_sources = set(FederatedConnectorSource)
        mapped_sources = set(FEDERATED_CONNECTOR_CLASS_MAP.keys())

        unmapped_sources = all_sources - mapped_sources

        if unmapped_sources:
            pytest.fail(
                f"FederatedConnectorSource values without connector mappings: "
                f"{[s.value for s in unmapped_sources]}"
            )
