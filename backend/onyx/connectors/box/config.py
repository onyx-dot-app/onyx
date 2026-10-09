from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class BoxConnectorConfig(ConnectorConfig):
    folder_ids: list[str] | None = None
    include_web_links: bool = False
    batch_size: int = INDEX_BATCH_SIZE
