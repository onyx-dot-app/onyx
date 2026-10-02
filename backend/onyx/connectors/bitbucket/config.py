from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class BitbucketConnectorConfig(ConnectorConfig):
    workspace: str
    repositories: str | None = None
    projects: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
