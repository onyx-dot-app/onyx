"""Jira Service Management connector package.

Reexports the connector for the registry's lazy import.
"""

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)

__all__ = ("JiraServiceManagementConnector",)
