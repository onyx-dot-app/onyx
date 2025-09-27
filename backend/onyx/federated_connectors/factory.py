"""Factory for creating federated connector instances."""

import importlib
from typing import Any
from typing import Type

from onyx.configs.constants import FederatedConnectorSource
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.federated_connectors.registry import FEDERATED_CONNECTOR_CLASS_MAP
from onyx.utils.logger import setup_logger

logger = setup_logger()


class FederatedConnectorMissingException(Exception):
    pass


# Cache for already imported federated connector classes
_federated_connector_cache: dict[FederatedConnectorSource, Type[FederatedConnector]] = (
    {}
)


def _load_federated_connector_class(
    source: FederatedConnectorSource,
) -> Type[FederatedConnector]:
    """Dynamically load and cache a federated connector class."""
    if source in _federated_connector_cache:
        return _federated_connector_cache[source]

    if source not in FEDERATED_CONNECTOR_CLASS_MAP:
        raise FederatedConnectorMissingException(
            f"Federated connector not found for source={source}"
        )

    mapping = FEDERATED_CONNECTOR_CLASS_MAP[source]

    try:
        module = importlib.import_module(mapping.module_path)
        connector_class = getattr(module, mapping.class_name)
        _federated_connector_cache[source] = connector_class
        return connector_class
    except (ImportError, AttributeError) as e:
        raise FederatedConnectorMissingException(
            f"Failed to import {mapping.class_name} from {mapping.module_path}: {e}"
        )


def get_federated_connector(
    source: FederatedConnectorSource,
    credentials: dict[str, Any],
) -> FederatedConnector:
    """Get an instance of the appropriate federated connector."""
    connector_cls = get_federated_connector_cls(source)
    return connector_cls(credentials)


def get_federated_connector_cls(
    source: FederatedConnectorSource,
) -> Type[FederatedConnector]:
    """Get the class of the appropriate federated connector."""
    return _load_federated_connector_class(source)
