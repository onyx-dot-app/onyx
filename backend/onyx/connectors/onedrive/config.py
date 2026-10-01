from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding


class OneDriveConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    COMMA_SEPARATED_FIELDS = frozenset({"users"})

    users: list[str] | None = None
    excluded_paths: list[str] | None = None
    treat_organization_link_as_public: bool = False
