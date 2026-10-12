"""Jira Service Management connector.

JSM customer requests are Jira issues living in service-desk projects, so
this connector rides the whole Jira indexing pipeline (JQL search,
checkpoints, slim docs, hierarchy nodes) and differs only in scope and
metadata:

- Every query is restricted to service-desk projects via
  ``projectType = service_desk``, unless the admin supplies a custom JQL
  query, which is taken verbatim as the escape hatch.
- Each emitted document is enriched from the Service Desk REST API
  (``rest/servicedeskapi/request/{issueKey}``) with the portal-facing fields
  a plain Jira issue does not expose: the status a customer sees, the
  service-desk / request-type ids, and the customer-portal link.

Documents keep the Jira issue browse URL as their ``Document.id`` so a
document keyed by this connector never collides with the same ticket indexed
through the Jira connector. Permission sync is intentionally not wired for
this source: JSM's customer-facing permission model differs from project
permissions, so JSM requests index with no ``external_access`` — the same
behavior the Jira connector exhibits on non-EE builds.
"""

from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, JiraIssue, _issue_key
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FIELD_SERVICE_DESK_STATUS = "service_desk_status"
_FIELD_SERVICE_DESK_ID = "service_desk_id"
_FIELD_REQUEST_TYPE_ID = "request_type_id"
_FIELD_PORTAL_LINK = "customer_portal_link"


class JiraServiceManagementConnector(JiraConnector):
    """Indexes every ticket in a Jira Service Management project (or across
    all service-desk projects when no project key is given)."""

    _SOURCE = DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Scope to service-desk projects only. A custom ``jql_query`` is
        honored verbatim (plus the connector's time window) so admins keep
        the escape hatch the Jira connector offers."""
        jql: str = super()._get_jql_query(start, end)
        if self.jql_query:
            return jql
        return f"({jql}) AND projectType = service_desk"

    @override
    def _process_issue(
        self, issue: JiraIssue, parent_hierarchy_raw_node_id: str | None
    ) -> Document | None:
        document: Document | None = super()._process_issue(
            issue, parent_hierarchy_raw_node_id
        )
        if document is None:
            return None
        document.source = self._SOURCE
        self._add_service_desk_metadata(document, _issue_key(issue))
        return document

    def _add_service_desk_metadata(self, document: Document, issue_key: str) -> None:
        """Merges Service Desk request fields into the document metadata.

        The servicedesk API 404s for issues that are not portal requests
        (for example agent-created issues in the project); those index
        unchanged. Other API failures propagate to the connector's per-issue
        failure handler rather than silently degrading the document."""
        request = self.source_operations.get_service_desk_request(issue_key=issue_key)
        if request is None:
            return
        metadata: dict[str, str | list[str]] = document.metadata
        if status := (request.get("currentStatus") or {}).get("status"):
            metadata[_FIELD_SERVICE_DESK_STATUS] = status
        if service_desk_id := request.get("serviceDeskId"):
            metadata[_FIELD_SERVICE_DESK_ID] = str(service_desk_id)
        if request_type_id := request.get("requestTypeId"):
            metadata[_FIELD_REQUEST_TYPE_ID] = str(request_type_id)
        if portal_link := (request.get("_links") or {}).get("web"):
            metadata[_FIELD_PORTAL_LINK] = portal_link

    @override
    def _get_project_permissions(
        self, project_key: str, add_prefix: bool = False
    ) -> ExternalAccess | None:
        """JSM docs index without ``external_access``: the Jira connector's
        project-permission ACLs are prefixed for the ``jira`` source and
        would never resolve against groups synced for this source."""
        return None
