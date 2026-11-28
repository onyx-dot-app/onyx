"""Jira Service Management (JSM) connector.

A JSM project is backed by a Jira project: its service desk requests are Jira
issues, so the connector pulls every ticket of a specified JSM project through
the same Atlassian REST APIs the Jira connector uses. The connector reuses the
Jira source-operations gateway, issue parsing, and hierarchy logic, and only
re-binds them to the ``DocumentSource.JSM`` source so documents are attributed
to Jira Service Management.

NOTE: This package intentionally does NOT eagerly import ``JsmConnector`` from
``onyx.connectors.jsm.connector``. The connector registry imports
``onyx.connectors.jsm.config`` while the Jira connector module is still being
initialized; eagerly importing the connector here would create a circular
import (``jira.connector`` -> ... -> ``jsm`` -> ``jira.connector``). Mirroring
the ``onyx.connectors.jira`` package, consumers import ``JsmConnector`` from
``onyx.connectors.jsm.connector`` directly.
"""

from onyx.connectors.jsm.config import (
    JSM_CONNECTOR_MAX_TICKET_SIZE,
    JSM_CONNECTOR_LABELS_TO_SKIP,
    JSM_SLIM_PAGE_SIZE,
)

__all__ = [
    "JSM_CONNECTOR_LABELS_TO_SKIP",
    "JSM_CONNECTOR_MAX_TICKET_SIZE",
    "JSM_SLIM_PAGE_SIZE",
]