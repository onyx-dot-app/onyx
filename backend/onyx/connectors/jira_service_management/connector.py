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

from collections.abc import Generator, Mapping
from typing import Any, ClassVar

import requests
from jira.exceptions import JIRAError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraCloudIdError,
    JiraSourceOperations,
    sla_payload_has_more_pages,
)
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
META_SERVICE_DESK_ID = "service_desk_id"
META_PORTAL_URL = "portal_url"


def _sla_breached_summary(sla_payload: Mapping[str, Any]) -> str | None:
    """Summarizes the SLA payload as "true"/"false" when it contains any
    cycle with a known breached state; None when nothing is known or when
    pagination is incomplete without a known breach."""
    cycles: list[bool] = []
    values = sla_payload.get("values")
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, Mapping):
                continue
            ongoing = value.get("ongoingCycle")
            if isinstance(ongoing, Mapping) and "breached" in ongoing:
                cycles.append(bool(ongoing["breached"]))
            completed_cycles = value.get("completedCycles")
            if isinstance(completed_cycles, list):
                cycles.extend(
                    bool(completed["breached"])
                    for completed in completed_cycles
                    if isinstance(completed, Mapping) and "breached" in completed
                )
    if any(cycles):
        return "true"
    if not cycles or sla_payload_has_more_pages(sla_payload):
        return None
    return "false"


def _apply_portal_request_metadata(
    document: Document, request: Mapping[str, Any]
) -> None:
    """Populate portal request metadata from a validated Service Desk mapping."""
    request_type_obj = request.get("requestType")
    if isinstance(request_type_obj, Mapping):
        request_type = request_type_obj.get("name")
        if isinstance(request_type, str) and request_type:
            document.metadata[META_REQUEST_TYPE] = request_type

    status_obj = request.get("currentStatus")
    if isinstance(status_obj, Mapping):
        portal_status = status_obj.get("status")
        if isinstance(portal_status, str) and portal_status:
            document.metadata[META_PORTAL_STATUS] = portal_status

    service_desk_id = request.get("serviceDeskId")
    if isinstance(service_desk_id, (str, int)) and not isinstance(service_desk_id, bool):
        document.metadata[META_SERVICE_DESK_ID] = str(service_desk_id)

    links_obj = request.get("_links")
    if isinstance(links_obj, Mapping):
        portal_url = links_obj.get("web")
        if isinstance(portal_url, str) and portal_url:
            document.metadata[META_PORTAL_URL] = portal_url


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management customer portal tickets."""

    connector_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT
    _project_type_cache: dict[str, str | None]

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Bind Jira credentials using the JSM source identifier."""
        self._project_type_cache = {}
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

    def _get_project_type_cache(self) -> dict[str, str | None]:
        cache: dict[str, str | None] | None = self.__dict__.get("_project_type_cache")
        if cache is None:
            cache = {}
            self._project_type_cache = cache
        return cache

    def _issue_project_type(self, issue: dict[str, Any]) -> str | None:
        """Return the Jira projectTypeKey for an issue, resolving and caching
        it via project metadata lookup when the issue payload omits it."""
        project = get_issue_field(issue, _FIELD_PROJECT)
        if not isinstance(project, Mapping):
            return None

        raw_type = project.get(_FIELD_PROJECT_TYPE_KEY)
        if isinstance(raw_type, str) and raw_type:
            return raw_type

        project_key = project.get(_FIELD_KEY)
        if not isinstance(project_key, str) or not project_key:
            return None

        cache = self._get_project_type_cache()
        if project_key in cache:
            return cache[project_key]

        resolved: str | None = None
        if self._source_operations is not None:
            try:
                resolved_project = self._source_operations.get_project(
                    project_key=project_key, fast=True
                )
            except (
                JiraApiError,
                JiraCloudIdError,
                ValueError,
                JIRAError,
                requests.RequestException,
            ) as exc:
                logger.debug(
                    "Could not resolve projectTypeKey for %s: %s",
                    project_key,
                    exc,
                )
            else:
                if isinstance(resolved_project, Mapping):
                    candidate = resolved_project.get(_FIELD_PROJECT_TYPE_KEY)
                    if isinstance(candidate, str) and candidate:
                        resolved = candidate

        cache[project_key] = resolved
        return resolved

    def _drops_issue(self, issue: dict[str, Any]) -> bool:
        """Everything-scope gate. With the default "Everything" scope the
        inherited JQL matches every project the credential can browse,
        including software projects. Drop any issue whose project type is not
        confirmed to be a service desk (after resolving and caching omitted
        project types). Project-only and JQL-only configurations have an
        explicit user scope, so the gate applies to Everything only."""
        if self.jira_project or self.jql_query:
            return False
        return self._issue_project_type(issue) != _PROJECT_TYPE_SERVICE_DESK

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
        """Convert a JSM issue into Onyx hierarchy nodes and enriched Documents."""
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
        if not isinstance(request, Mapping):
            logger.debug(
                "No JSM portal metadata for %s: request lookup returned "
                "nothing (JSM absent, no service-desk access, or malformed payload).",
                issue_key,
            )
        else:
            _apply_portal_request_metadata(document, request)

        sla = self.source_operations.get_service_desk_sla(
            issue_key=issue_key, fast=True
        )
        if not isinstance(sla, Mapping):
            logger.debug("No JSM SLA data for %s.", issue_key)
        else:
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
