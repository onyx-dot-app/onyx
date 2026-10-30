"""Jira Service Management (JSM) connector package."""

from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)

__all__ = [
    "JiraServiceManagementConnector",
    "JiraServiceManagementConnectorConfig",
]
