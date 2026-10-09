from onyx.connectors.connector_config import ConnectorConfig


class GongConnectorConfig(ConnectorConfig):
    workspaces: list[str] | None = None
    hide_user_info: bool = False
