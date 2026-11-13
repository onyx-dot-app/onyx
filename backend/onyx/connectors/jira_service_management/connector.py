"""Jira Service Management (JSM) connector.

Indexes the tickets (customer requests) of a Jira Service Management project
as their own document source, enriching each one with customer-portal
metadata from the JSM Service Desk REST API: request type, portal status and
an SLA breach summary.

All indexing, checkpointing, slim-listing, hierarchy and permission-sync
behavior is inherited from the Jira connector - a JSM project is a regular
Jira project of type ``service_desk``. Only two things change here:

1. Indexed documents carry ``DocumentSource.JIRA_SERVICE_MANAGEMENT`` so they
   stay distinguishable (and independently filterable) from plain Jira issues.
2. Each document's metadata gains the JSM portal fields when the Service Desk
   API answers. Enrichment is best effort: when JSM is not installed, the
   credential lacks service-desk access, or a single request lookup fails,
   the ticket still indexes with the regular Jira fields.
"""

from collections.abc import Generator
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira.utils import get_issue_field
from onyx.connectors.models import Document, HierarchyNode
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FIELD_KEY = "key"
_FIELD_PROJECT = "project"
_FIELD_PROJECT_TYPE_KEY = "projectTypeKey"
_PROJECT_TYPE_SERVICE_DESK = "service_desk"

# Extra metadata keys this connector adds on top of the Jira ones.
META_REQUEST_TYPE = "request_type"
META_PORTAL_STATUS = "portal_status"
META_SLA_BREACHED = "sla_breached"


def _sla_breached_summary(sla_payload: dict[str, Any]) -> str | None:
    """Summarizes the SLA payload as "true"/"false" when it contains any
    cycle with a known breached state; None when nothing is known."""
    cycles: list[bool] = []
    for value in sla_payload.get("values") or []:
        ongoing = value.get("ongoingCycle") or {}
        if "breached" in ongoing:
            cycles.append(bool(ongoing["breached"]))
        cycles.extend(
            bool(completed["breached"])
            for completed in value.get("completedCycles") or []
            if "breached" in completed
        )
    if not cycles:
        return None
    return "true" if any(cycles) else "false"


class JiraServiceManagementConnector(JiraConnector):
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._source_operations = JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
            ),
            connector_specific_config={
                "jira_base_url": self.jira_base,
                "scoped_token": self.scoped_token,
            },
        )
        return None

    def _issue_project_type(self, issue: dict[str, Any]) -> str | None:
        project = get_issue_field(issue, _FIELD_PROJECT)
        return project.get(_FIELD_PROJECT_TYPE_KEY) if project else None

    def _drops_issue(self, issue: dict[str, Any]) -> bool:
        """Everything-scope gate. With the default "Everything" scope the
        inherited JQL matches every project the credential can browse,
        including software projects. Ordinary Jira issues must not index
        under the JSM source, so drop issues whose project is known not to
        be a service desk. JQL-only configurations also leave jira_project
        unset, but their scope is the user's explicit query, so the gate
        applies to Everything only. When the payload omits projectTypeKey
        (some Data Center versions) the issue indexes and enrichment stays
        best effort, as documented."""
        project_type = self._issue_project_type(issue)
        return (
            not self.jira_project
            and not self.jql_query
            and project_type is not None
            and project_type != _PROJECT_TYPE_SERVICE_DESK
        )

    def _include_issue_in_slim_listing(self, issue: dict[str, Any]) -> bool:
        """Applies the Everything-scope gate to slim-document listing too.
        Pruning diffs this listing against the indexed set; without the gate
        an issue that moved out of its service desk project would keep a
        stale JSM document forever."""
        return not self._drops_issue(issue)

    def _issue_to_items(
        self,
        issue: dict[str, Any],
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        if self._drops_issue(issue):
            return
        # In Project/JQL scopes the user picked the scope deliberately (JQL
        # may span project types); only skip the enrichment lookups for known
        # non-service-desk projects, which can never have portal metadata.
        enrich = self._issue_project_type(issue) in (None, _PROJECT_TYPE_SERVICE_DESK)
        for item in super()._issue_to_items(
            issue, seen_hierarchy_node_ids, include_permissions
        ):
            if isinstance(item, Document):
                self._mark_and_enrich_jsm_document(item, enrich=enrich)
            yield item

    def _mark_and_enrich_jsm_document(
        self, document: Document, *, enrich: bool = True
    ) -> None:
        """Sets the JSM source and adds portal metadata, best effort."""
        document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
        if not enrich:
            return

        issue_key = document.metadata.get(_FIELD_KEY)
        if not isinstance(issue_key, str) or not issue_key:
            return

        request = self.source_operations.get_service_desk_request(
            issue_key=issue_key, fast=True
        )
        if request is None:
            logger.debug(
                "No JSM portal metadata for %s: request lookup returned "
                "nothing (JSM absent or no service-desk access).",
                issue_key,
            )
        if request is not None:
            request_type = (request.get("requestType") or {}).get("name")
            if request_type:
                document.metadata[META_REQUEST_TYPE] = request_type
            portal_status = (request.get("currentStatus") or {}).get("status")
            if portal_status:
                document.metadata[META_PORTAL_STATUS] = portal_status

        sla = self.source_operations.get_service_desk_sla(
            issue_key=issue_key, fast=True
        )
        if sla is None:
            logger.debug("No JSM SLA data for %s.", issue_key)
        if sla is not None:
            summary = _sla_breached_summary(sla)
            if summary is not None:
                document.metadata[META_SLA_BREACHED] = summary

    def validate_connector_settings(self) -> None:
        """Regular Jira validation, plus a heads-up log when the configured
        project is not a service desk (still allowed - JQL scopes may span
        project types intentionally)."""
        super().validate_connector_settings()
        if self.jira_project is None or not self.jira_project:
            return
        try:
            project = self.source_operations.get_project(project_key=self.jira_project)
        except Exception:
            return  # the parent validator already reports unreachable projects
        project_type = (project or {}).get("projectTypeKey")
        if project_type and project_type != "service_desk":
            logger.warning(
                "Project %s has projectTypeKey '%s', not 'service_desk'. "
                "Tickets will still be indexed; JSM portal metadata may be "
                "absent.",
                self.jira_project,
                project_type,
            )
