"""Factory for creating federated connector instances."""

from typing import Any

from onyx.configs.constants import FederatedConnectorSource
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.federated_connectors.slack.federated_connector import SlackFederatedConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_federated_connector(
    source: FederatedConnectorSource,
    credentials: dict[str, Any],
) -> FederatedConnector:
    """Get an instance of the appropriate federated connector."""
    connector_cls = get_federated_connector_cls(source)
    return connector_cls(credentials)


def get_federated_connector_cls(
    source: FederatedConnectorSource,
) -> type[FederatedConnector]:
    """Get the class of the appropriate federated connector."""
    if source == FederatedConnectorSource.FEDERATED_SLACK:
        return SlackFederatedConnector
    else:
        raise ValueError(f"Unsupported federated connector source: {source}")
