"""Configuration for the Jira Service Management connector.

The connector intentionally reuses every Jira scope and behavior field: a JSM
project is a regular Jira project of type ``service_desk``, so project keys,
JQL, label skipping and the comment blacklist all apply unchanged.
"""

from onyx.connectors.jira.config import JiraConnectorConfig


class JiraServiceManagementConnectorConfig(JiraConnectorConfig):
    """Same fields as Jira; registered separately so the source keeps its own
    document type, icon and credential family binding."""
