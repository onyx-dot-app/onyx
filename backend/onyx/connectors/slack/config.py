from onyx.configs.app_configs import INDEX_BATCH_SIZE, SLACK_NUM_THREADS
from onyx.connectors.connector_config import ConnectorConfig


class SlackConnectorConfig(ConnectorConfig):
    channels: list[str] | None = None
    channel_regex_enabled: bool = False
    exclude_channels: list[str] | None = None
    exclude_channel_regex_enabled: bool = False
    include_bot_messages: bool = False
    batch_size: int = INDEX_BATCH_SIZE
    num_threads: int = SLACK_NUM_THREADS
    use_redis: bool = True
