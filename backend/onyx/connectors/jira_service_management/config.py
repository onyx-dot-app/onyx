from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.jira.config import JiraCredentialBinding


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    project_key: str | None = None
    service_desk_id: int | None = None
    comment_email_blacklist: list[str] | None = None
    batch_size: int = INDEX_BATCH_SIZE
    labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP
    jql_query: str | None = None
