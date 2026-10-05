from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class EgnyteConnectorConfig(ConnectorConfig):
    folder_path: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
