from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.jira.config import JiraCredentialBinding


class JiraServiceManagementConnectorConfig(JiraCredentialBinding, ConnectorConfig):
    """Reuses the Jira credential binding but is its own shape: the JSM
    connector requires ``project_key`` and adds the internal-comment and
    attachment toggles, so the shared Jira config cannot describe it.
    """

    project_key: str
    comment_email_blacklist: list[str] | None = None
    batch_size: int = INDEX_BATCH_SIZE
    labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP
    jql_query: str | None = None
    include_internal_comments: bool = False
    include_attachments: bool = False
