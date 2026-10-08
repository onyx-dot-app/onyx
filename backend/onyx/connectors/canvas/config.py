from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding


class CanvasCredentialBinding(CredentialBinding):
    canvas_base_url: str


class CanvasConnectorConfig(CanvasCredentialBinding, ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
