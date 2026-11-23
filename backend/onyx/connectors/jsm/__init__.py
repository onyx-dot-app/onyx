"""Jira Service Management (JSM) connector.

A JSM project is backed by a Jira project: its service desk requests are Jira
issues, so the connector pulls every ticket of a specified JSM project through
the same Atlassian REST APIs the Jira connector uses. The connector reuses the
Jira source-operations gateway, issue parsing, and hierarchy logic, and only
re-binds them to the ``DocumentSource.JSM`` source so documents are attributed
to Jira Service Management.
"""

from onyx.connectors.jsm.config import (
    JSM_CONNECTOR_MAX_TICKET_SIZE,
    JSM_CONNECTOR_LABELS_TO_SKIP,
    JSM_SLIM_PAGE_SIZE,
)
from onyx.connectors.jsm.connector import JsmConnector

__all__ = [
    "JsmConnector",
    "JSM_CONNECTOR_LABELS_TO_SKIP",
    "JSM_CONNECTOR_MAX_TICKET_SIZE",
    "JSM_SLIM_PAGE_SIZE",
]