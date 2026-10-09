from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
)
from onyx.connectors.connector_config import ConnectorConfig


class NotionConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    recursive_index_enabled: bool = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP
    root_page_id: str | None = None
