from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding


class JiraServiceManagementConnectorBinding(CredentialBinding):
    jsm_base_url: str


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementConnectorBinding, ConnectorConfig
):
    service_desk_id: str | None = None
    jql_query: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
