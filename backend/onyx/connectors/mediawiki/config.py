from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class MediaWikiConnectorConfig(ConnectorConfig):
    hostname: str
    categories: list[str]
    pages: list[str]
    recurse_depth: int
    language_code: str = "en"
    batch_size: int = INDEX_BATCH_SIZE
