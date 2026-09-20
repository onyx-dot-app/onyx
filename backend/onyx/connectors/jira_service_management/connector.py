"""Jira Service Management connector.

Jira Service Management (JSM) shares its REST surface with Jira Software:
issues are issues, JQL is JQL, and the same Atlassian credentials work. The
differences that matter for indexing are:

- JSM projects are service desks; a JSM project key scopes tickets the same
  way a software project key does.
- JSM "customer requests" (portal-raised tickets) are regular issues behind
  the scenes. JQL ``project = <KEY>`` returns both internal work items and
  portal requests the credentials can see.
- A JSM-specific connector lets users pick a service desk project without
  fighting the software-project UI copy and lets Onyx treat service tickets
  distinctly (DocumentSource.JIRA_SERVICE_MANAGEMENT).

Rather than duplicating ~1k lines of Jira machinery, this connector
subclasses ``JiraConnector`` unchanged. Pagination, checkpointing, slim-doc
retrieval, permission sync, validation, and document processing are all
inherited; only the connector's identity and its frontend contract differ.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector

__all__ = ("JiraServiceManagementConnector",)


class JiraServiceManagementConnector(JiraConnector):
    """Indexes tickets from a Jira Service Management project.

    Behaves exactly like the Jira connector (same checkpoint/JQL/permission
    machinery) but is registered under its own DocumentSource so users can
    add a service desk as a distinct connector and Onyx can distinguish
    service tickets from software issues in metadata and filters.
    """

    source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT
