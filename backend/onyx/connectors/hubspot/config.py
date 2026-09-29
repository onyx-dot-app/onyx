from enum import StrEnum

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class HubSpotObjectType(StrEnum):
    TICKETS = "tickets"
    COMPANIES = "companies"
    DEALS = "deals"
    CONTACTS = "contacts"


class HubSpotConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    access_token: str | None = None
    object_types: list[HubSpotObjectType] | None = None
