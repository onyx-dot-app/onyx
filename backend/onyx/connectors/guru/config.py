from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class GuruConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    guru_user: str | None = None
    guru_user_token: str | None = None
