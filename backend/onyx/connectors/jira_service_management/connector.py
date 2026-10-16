"""Jira Service Management (JSM) connector.

JSM requests are Jira issues in a "service_desk" project, served by the same
REST API. This connector reuses the Jira connector's checkpointed indexing,
slim retrieval and hierarchy, and adds:

* a required service project key (validated to be a JSM project),
* its own ``DocumentSource`` so tickets can be filtered separately from Jira,
* JSM request metadata (request type, customer-facing status, portal link,
  SLA state, organizations) read from the request custom fields.
"""

from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector, JiraIssue
from onyx.connectors.models import ConnectorMissingCredentialError

JSM_PROJECT_TYPE_KEY = "service_desk"

FIELD_REQUEST_TYPE = "request_type"
FIELD_REQUEST_STATUS = "request_status"
FIELD_REQUEST_PORTAL_URL = "request_portal_url"
FIELD_ORGANIZATIONS = "organizations"
FIELD_SLA_BREACHED = "sla_breached"
FIELD_SLA_ONGOING = "sla_ongoing"


def _is_customer_request_field(value: Any) -> bool:
    # The "Customer Request Type" custom field (id differs per site).
    return isinstance(value, dict) and isinstance(value.get("requestType"), dict)


def _is_sla_field(value: Any) -> bool:
    # JSM SLA custom fields ("Time to first response", "Time to resolution", ...).
    return isinstance(value, dict) and (
        "ongoingCycle" in value or "completedCycles" in value
    )


def _is_organizations_field(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(org, dict) and "name" in org and "_links" in org for org in value
        )
    )


def extract_jsm_metadata(issue: JiraIssue) -> dict[str, str | list[str]]:
    """JSM request metadata from a raw issue's custom fields.

    The fields are site-specific ``customfield_*`` ids, so they are recognized
    by shape rather than id. Missing fields are skipped.
    """
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return {}

    metadata: dict[str, str | list[str]] = {}
    breached: list[str] = []
    ongoing: list[str] = []

    for key, value in fields.items():
        if not key.startswith("customfield_") or value is None:
            continue

        if _is_customer_request_field(value):
            if name := value["requestType"].get("name"):
                metadata[FIELD_REQUEST_TYPE] = str(name)
            current_status = value.get("currentStatus")
            if isinstance(current_status, dict) and current_status.get("status"):
                metadata[FIELD_REQUEST_STATUS] = str(current_status["status"])
            links = value.get("_links")
            if isinstance(links, dict) and links.get("web"):
                metadata[FIELD_REQUEST_PORTAL_URL] = str(links["web"])

        elif _is_sla_field(value):
            sla_name = str(value.get("name") or key)
            cycle = value.get("ongoingCycle")
            completed = value.get("completedCycles") or []
            is_breached = (isinstance(cycle, dict) and cycle.get("breached")) or any(
                isinstance(c, dict) and c.get("breached") for c in completed
            )
            if is_breached:
                breached.append(sla_name)
            if isinstance(cycle, dict) and not cycle.get("paused", False):
                ongoing.append(sla_name)

        elif _is_organizations_field(value):
            metadata[FIELD_ORGANIZATIONS] = sorted(str(org["name"]) for org in value)

    if breached:
        metadata[FIELD_SLA_BREACHED] = sorted(breached)
    if ongoing:
        metadata[FIELD_SLA_ONGOING] = sorted(ongoing)
    return metadata


class JiraServiceManagementConnector(JiraConnector):
    document_source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        if not (project_key or "").strip():
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=None,
            scoped_token=scoped_token,
        )

    def _extra_issue_metadata(self, issue: JiraIssue) -> dict[str, str | list[str]]:
        return extract_jsm_metadata(issue)

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        try:
            project = self.source_operations.get_project(
                project_key=self.jira_project  # ty: ignore[invalid-argument-type]
            )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            return

        project_type = project.get("projectTypeKey")
        if project_type and project_type != JSM_PROJECT_TYPE_KEY:
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is a '{project_type}' project, "
                "not a Jira Service Management (service_desk) project. "
                "Use the Jira connector for it instead."
            )
