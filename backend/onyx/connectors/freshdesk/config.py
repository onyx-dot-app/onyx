from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class FreshdeskConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
