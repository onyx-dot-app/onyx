"""Factory for creating federated connector instances."""

from typing import Dict
from typing import Type

from onyx.configs.constants import FederatedConnectorSource
from onyx.federated_connectors.base import FederatedConnectorBase
from onyx.federated_connectors.slack.federated_connector import SlackFederatedConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Registry of federated connector implementations
FEDERATED_CONNECTOR_REGISTRY: Dict[
    FederatedConnectorSource, Type[FederatedConnectorBase]
] = {
    FederatedConnectorSource.FEDERATED_SLACK: SlackFederatedConnector,
}


def get_federated_connector(source: FederatedConnectorSource) -> FederatedConnectorBase:
    """
    Factory function to get the appropriate federated connector instance.

    Args:
        source: The federated connector source type

    Returns:
        An instance of the appropriate federated connector

    Raises:
        ValueError: If the source is not supported
    """
    if source not in FEDERATED_CONNECTOR_REGISTRY:
        raise ValueError(f"Unsupported federated connector source: {source}")

    connector_class = FEDERATED_CONNECTOR_REGISTRY[source]
    logger.info(f"Creating federated connector instance for source: {source}")

    return connector_class()


def register_federated_connector(
    source: FederatedConnectorSource, connector_class: Type[FederatedConnectorBase]
) -> None:
    """
    Register a new federated connector implementation.

    This allows for dynamic registration of new connector types.

    Args:
        source: The federated connector source type
        connector_class: The class implementing FederatedConnectorBase
    """
    if not issubclass(connector_class, FederatedConnectorBase):
        raise ValueError(
            f"Connector class {connector_class} must inherit from FederatedConnectorBase"
        )

    FEDERATED_CONNECTOR_REGISTRY[source] = connector_class
    logger.info(f"Registered federated connector for source: {source}")
