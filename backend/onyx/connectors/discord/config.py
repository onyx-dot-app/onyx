from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class DiscordConnectorConfig(ConnectorConfig):
    COMMA_SEPARATED_FIELDS = frozenset({"server_ids"})

    server_ids: list[str] | None = None
    channel_names: list[str] | None = None
    # YYYY-MM-DD
    start_date: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
