"""Registry mapping for federated connector classes."""

from pydantic import BaseModel

from onyx.configs.constants import FederatedConnectorSource


class FederatedConnectorMapping(BaseModel):
    module_path: str
    class_name: str


# Mapping of FederatedConnectorSource to connector details for lazy loading
FEDERATED_CONNECTOR_CLASS_MAP = {
    FederatedConnectorSource.FEDERATED_SLACK: FederatedConnectorMapping(
        module_path="onyx.federated_connectors.slack.federated_connector",
        class_name="SlackFederatedConnector",
    ),
}
