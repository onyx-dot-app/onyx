"""Jira Service Management connector for Onyx.

Indexes service desk tickets, customer requests, comments, and attachment
metadata from Jira Service Management (Cloud or Server/Data Center).
"""

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)

__all__ = ["JiraServiceManagementConnector"]
