from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class LoopioConnectorConfig(ConnectorConfig):
    loopio_stack_name: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
