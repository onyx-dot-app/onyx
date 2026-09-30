from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class CodaConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    index_page_content: bool = True
    workspace_id: str | None = None
