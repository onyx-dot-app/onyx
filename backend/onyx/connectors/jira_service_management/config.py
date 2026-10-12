from onyx.connectors.jira.config import JiraConnectorConfig


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Same fields as the Jira connector (base URL, scoped-token flag,
    project key / JQL scope, comment blacklist). The connector itself fixes
    scope to service-desk projects; the config carries nothing extra."""
