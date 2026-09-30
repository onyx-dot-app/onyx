from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_LABELS_TO_SKIP,
    CONFLUENCE_TIMEZONE_OFFSET,
    CONTINUE_ON_CONNECTOR_FAILURE,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.connector_config import ConnectorConfig


class ConfluenceConnectorConfig(ConnectorConfig):
    wiki_base: str
    is_cloud: bool
    space: str = ""
    page_id: str = ""
    index_recursively: bool = False
    cql_query: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
    continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE
    labels_to_skip: list[str] = CONFLUENCE_CONNECTOR_LABELS_TO_SKIP
    timezone_offset: float = CONFLUENCE_TIMEZONE_OFFSET
    scoped_token: bool = False
    include_attachments: bool = True
