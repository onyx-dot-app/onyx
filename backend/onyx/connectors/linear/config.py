from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class LinearConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
