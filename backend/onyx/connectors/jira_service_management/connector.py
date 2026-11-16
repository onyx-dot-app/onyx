"""Jira Service Management (JSM) connector.

JSM service projects are Jira projects with the ``service_desk`` project type,
so requests are read through the Jira REST API that the Jira connector already
uses. This connector reuses that indexing, checkpointing, slim listing and
permission logic, scopes it to a single service project, tags documents with
their own source, and adds JSM-specific metadata (request type, customer
facing status and SLAs) to each request.
"""

from typing import Any, ClassVar

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger

logger = setup_logger()

SERVICE_DESK_PROJECT_TYPE = "service_desk"
HTTP_NOT_FOUND = 404

# Metadata keys added to JSM request documents.
METADATA_REQUEST_TYPE = "request_type"
METADATA_REQUEST_STATUS = "request_status"
METADATA_SLA_BREACHED = "sla_breached"
METADATA_SLA_PREFIX = "sla"

_FIELDS = "fields"
_REQUEST_TYPE = "requestType"
_CURRENT_STATUS = "currentStatus"
_STATUS = "status"
_NAME = "name"
_ONGOING_CYCLE = "ongoingCycle"
_COMPLETED_CYCLES = "completedCycles"
_BREACHED = "breached"
_REMAINING_TIME = "remainingTime"
_FRIENDLY = "friendly"

_SLA_BREACHED = "breached"
_SLA_MET = "met"
_SLA_ONGOING = "ongoing"
_SLA_UNKNOWN = "unknown"

_COMMENT = "comment"
_COMMENTS = "comments"
# Jira Cloud marks each JSM comment as public (shared with customers) or an
# internal note with ``jsdPublic``. Server / Data Center (and older Cloud
# payloads) carry the same flag in the ``sd.public.comment`` property.
_JSD_PUBLIC = "jsdPublic"
_PROPERTIES = "properties"
_PROPERTY_KEY = "key"
_PROPERTY_VALUE = "value"
_SD_PUBLIC_COMMENT = "sd.public.comment"
_INTERNAL = "internal"


def _is_request_type_value(value: Any) -> bool:
    """The "Customer Request Type" custom field (``com.atlassian.servicedesk:
    vp-origin``) holds an object with a ``requestType`` entry."""
    return isinstance(value, dict) and isinstance(value.get(_REQUEST_TYPE), dict)


def _is_request_status_value(value: Any) -> bool:
    """Moved requests can keep ``currentStatus`` without a ``requestType``."""
    return (
        isinstance(value, dict)
        and isinstance(value.get(_CURRENT_STATUS), dict)
        and not _is_sla_value(value)
    )


def is_internal_comment(comment: dict[str, Any]) -> bool:
    """Whether a JSM comment must be treated as an internal note.

    Fails closed: a comment counts as public only when Jira explicitly marks
    it so (``jsdPublic: true`` or ``sd.public.comment`` with
    ``internal: false``). Unknown visibility is treated as internal.
    """
    jsd_public: Any = comment.get(_JSD_PUBLIC)
    if jsd_public is False:
        return True
    explicit_public: bool = jsd_public is True
    for prop in comment.get(_PROPERTIES) or []:
        if not isinstance(prop, dict) or prop.get(_PROPERTY_KEY) != _SD_PUBLIC_COMMENT:
            continue
        value: Any = prop.get(_PROPERTY_VALUE)
        internal: Any = value.get(_INTERNAL) if isinstance(value, dict) else None
        if internal is True:
            return True
        if internal is False:
            explicit_public = True
    return not explicit_public


def without_internal_comments(issue: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``issue`` without internal notes; public comments are kept."""
    fields: Any = issue.get(_FIELDS)
    if not isinstance(fields, dict):
        return issue
    comment_field: Any = fields.get(_COMMENT)
    if not isinstance(comment_field, dict):
        return issue
    comments: Any = comment_field.get(_COMMENTS)
    if not isinstance(comments, list):
        return issue
    public = [
        c for c in comments if not (isinstance(c, dict) and is_internal_comment(c))
    ]
    if len(public) == len(comments):
        return issue
    return {
        **issue,
        _FIELDS: {**fields, _COMMENT: {**comment_field, _COMMENTS: public}},
    }


def _is_sla_value(value: Any) -> bool:
    """SLA custom fields (``com.atlassian.servicedesk:sla-field``) hold an
    object with a name and ongoing and/or completed cycles."""
    return (
        isinstance(value, dict)
        and isinstance(value.get(_NAME), str)
        and (_ONGOING_CYCLE in value or _COMPLETED_CYCLES in value)
    )


def _sla_summary(sla: dict[str, Any]) -> tuple[str, bool]:
    """A readable state for one SLA and whether it is breached.

    JSM custom field ids differ per site, so SLAs are found by value shape
    rather than by field id.
    """
    ongoing: Any = sla.get(_ONGOING_CYCLE)
    if isinstance(ongoing, dict):
        if ongoing.get(_BREACHED):
            return _SLA_BREACHED, True
        remaining: Any = ongoing.get(_REMAINING_TIME)
        friendly: Any = (
            remaining.get(_FRIENDLY) if isinstance(remaining, dict) else None
        )
        return (
            f"{_SLA_ONGOING} ({friendly} remaining)" if friendly else _SLA_ONGOING
        ), False

    completed: Any = sla.get(_COMPLETED_CYCLES) or []
    if isinstance(completed, list) and completed:
        last: Any = completed[-1]
        if isinstance(last, dict) and last.get(_BREACHED):
            return _SLA_BREACHED, True
        return _SLA_MET, False
    # No cycle has started yet (e.g. the SLA's start condition is not met).
    return _SLA_UNKNOWN, False


def _sla_metadata_key(sla_name: str) -> str:
    slug = "_".join(sla_name.lower().split())
    return f"{METADATA_SLA_PREFIX}_{slug}"


def extract_jsm_metadata(issue: dict[str, Any]) -> dict[str, str | list[str]]:
    """JSM-specific metadata from a raw issue as the Jira REST API returns it."""
    metadata: dict[str, str | list[str]] = {}
    fields: Any = issue.get(_FIELDS) or {}
    if not isinstance(fields, dict):
        return metadata

    breached_slas: list[str] = []
    for value in fields.values():
        if _is_request_type_value(value) or _is_request_status_value(value):
            request_type: Any = value.get(_REQUEST_TYPE)
            if isinstance(request_type, dict) and request_type.get(_NAME):
                metadata[METADATA_REQUEST_TYPE] = str(request_type[_NAME])
            current_status: Any = value.get(_CURRENT_STATUS)
            if isinstance(current_status, dict) and current_status.get(_STATUS):
                metadata[METADATA_REQUEST_STATUS] = str(current_status[_STATUS])
        elif _is_sla_value(value):
            state, breached = _sla_summary(value)
            metadata[_sla_metadata_key(value[_NAME])] = state
            if breached:
                breached_slas.append(value[_NAME])

    if breached_slas:
        metadata[METADATA_SLA_BREACHED] = breached_slas
    return metadata


class JiraServiceManagementConnector(JiraConnector):
    """Indexes the requests of one Jira Service Management project."""

    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

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
                "Jira Service Management connector requires a project key."
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

    def _issue_for_document(self, issue: dict[str, Any]) -> dict[str, Any]:
        # Internal notes are agent-only and must not leak into the index.
        return without_internal_comments(issue)

    def _extra_issue_metadata(
        self, issue: dict[str, Any]
    ) -> dict[str, str | list[str]]:
        return extract_jsm_metadata(issue)

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        project_key: str = self.jira_project or ""
        try:
            project: dict[str, Any] = self.source_operations.get_project(
                project_key=project_key
            )
        except JiraApiError as e:
            if e.status_code == HTTP_NOT_FOUND:
                raise ConnectorValidationError(
                    f"Jira Service Management project '{project_key}' does not "
                    "exist or the credential cannot browse it."
                ) from e
            self._handle_jira_connector_settings_error(e)
            return
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            return

        project_type: Any = project.get("projectTypeKey")
        if project_type != SERVICE_DESK_PROJECT_TYPE:
            raise ConnectorValidationError(
                f"Project '{project_key}' is not a Jira Service Management "
                f"project (project type: '{project_type}'). Use the Jira "
                "connector for software and business projects."
            )
