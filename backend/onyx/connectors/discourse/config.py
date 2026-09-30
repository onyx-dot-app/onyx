from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class DiscourseConnectorConfig(ConnectorConfig):
    base_url: str
    categories: list[str] | None = None
    batch_size: int = INDEX_BATCH_SIZE
