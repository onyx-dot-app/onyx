from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig


class DiscourseConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    categories: list[str] | None = None
    batch_size: int = INDEX_BATCH_SIZE
