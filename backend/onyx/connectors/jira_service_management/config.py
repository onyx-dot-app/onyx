from onyx.connectors.jira.config import (
    JiraConnectorConfig,
    jira_planning_rule,
)


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Configuration for Jira Service Management (JSM) connector."""

    pass


__all__ = ["JiraServiceManagementConnectorConfig", "jira_planning_rule"]
