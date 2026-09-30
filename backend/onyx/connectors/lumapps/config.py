from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class LumAppsConnectorConfig(ConnectorConfig):
    base_url: str
    organization_id: str
    instance_ids: list[str] | None = None
    custom_content_types: list[str] | None = None
    lang: str = "en"
    batch_size: int = INDEX_BATCH_SIZE
