"""Factory for creating federated connector instances."""

from typing import Any
from typing import Dict

from onyx.configs.constants import FederatedConnectorSource
from onyx.federated_connectors.interfaces import FederatedConnectorBase
from onyx.federated_connectors.slack.federated_connector import SlackFederatedConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_federated_connector(
    source: FederatedConnectorSource, credentials: Dict[str, Any] | None = None
) -> FederatedConnectorBase:
    """
    Factory function to get the appropriate federated connector instance.

    Args:
        source: The federated connector source type
        credentials: Optional credentials to initialize the connector with

    Returns:
        An instance of the appropriate federated connector

    Raises:
        ValueError: If the source is not supported
    """
    logger.info(f"Creating federated connector instance for source: {source}")

    if source == FederatedConnectorSource.FEDERATED_SLACK:
        if credentials is None:
            credentials = {}
        return SlackFederatedConnector(credentials=credentials)
    else:
        raise ValueError(f"Unsupported federated connector source: {source}")
