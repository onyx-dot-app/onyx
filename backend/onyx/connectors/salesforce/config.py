from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class SalesforceConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    requested_objects: list[str] | None = None
    custom_query_config: str | None = None
