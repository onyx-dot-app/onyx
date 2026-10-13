from onyx.connectors.jira.config import JiraConnectorConfig


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Same settings as the Jira connector: JSM requests are Jira issues, so
    the base URL, project key, JQL, and comment blacklist apply unchanged.
    A separate config class keeps the source's stored config and its
    credential binding independent of the plain Jira source."""
