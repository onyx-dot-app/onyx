from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class AxeroConnectorConfig(ConnectorConfig):
    spaces: list[str] | None = None
    include_article: bool = True
    include_blog: bool = True
    include_wiki: bool = True
    include_forum: bool = True
    batch_size: int = INDEX_BATCH_SIZE
