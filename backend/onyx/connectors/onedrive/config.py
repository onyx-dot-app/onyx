from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)


class OneDriveConnectorConfig(ConnectorConfig):
    users: list[str] | None = None
    excluded_paths: list[str] | None = None
    treat_organization_link_as_public: bool = False
    authority_host: str = DEFAULT_AUTHORITY_HOST
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
