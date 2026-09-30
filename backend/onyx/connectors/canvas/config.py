from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class CanvasConnectorConfig(ConnectorConfig):
    canvas_base_url: str
    batch_size: int = INDEX_BATCH_SIZE
