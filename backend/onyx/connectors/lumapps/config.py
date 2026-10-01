from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig


class LumAppsCredentialBinding(BaseUrlCredentialBinding):
    organization_id: str


class LumAppsConnectorConfig(LumAppsCredentialBinding, ConnectorConfig):
    COMMA_SEPARATED_FIELDS = frozenset({"instance_ids"})

    instance_ids: list[str] | None = None
    custom_content_types: list[str] | None = None
    lang: str = "en"
    batch_size: int = INDEX_BATCH_SIZE
