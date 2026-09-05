"""Jira Service Management connector.

Service Management requests are Jira issues in a service desk project, so this
connector builds on the Jira connector. It reuses the Jira client, the JQL
pagination, the checkpoint logic, and the project permissions. It adds the
Service Management fields (request type and SLA state), and it stamps its own
document source.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Jira issues also power the plain Jira connector, so Service Management documents
# get their own id namespace. This keeps both connectors usable at the same time.
DOC_ID_PREFIX = "jira_service_management:"

SERVICE_DESK_PROJECT_TYPE = "service_desk"

_REQUEST_TYPE_METADATA_KEY = "request_type"
_SLA_METADATA_PREFIX = "sla_"

# Jira exposes the request type and the SLA fields as custom fields. Cloud and
# Data Center use different names for the request type field, so match on both
# the schema key and the field name.
_REQUEST_TYPE_SCHEMA_KEYS = {
    "com.atlassian.servicedesk:vp-origin",
    "com.atlassian.servicedesk:sd-request-type",
}
_REQUEST_TYPE_FIELD_NAMES = {"request type", "customer request type"}
_SLA_SCHEMA_KEY = "com.atlassian.servicedesk:sd-sla-field"
_SLA_SCHEMA_TYPE = "sla"

_SLA_STATE_BREACHED = "breached"
_SLA_STATE_ONGOING = "ongoing"
_SLA_STATE_MET = "met"


@dataclass(frozen=True)
class JsmFieldIds:
    """Ids of the Service Management custom fields of a Jira instance."""

    request_type: str | None
    slas: dict[str, str]


def _attribute_or_key(value: Any, key: str) -> Any:
    """Read a key of a Service Management field value.

    The Jira library gives dicts for bulk-fetched issues and dynamic resource
    objects for searched issues, so support both shapes.
    """
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)  # ods: ignore[getattr] dynamic Jira resource payload
    return None


def _is_request_type_field(field: dict[str, Any]) -> bool:
    schema = field.get("schema") or {}
    if schema.get("custom") in _REQUEST_TYPE_SCHEMA_KEYS:
        return True
    name = field.get("name") or ""
    return name.strip().lower() in _REQUEST_TYPE_FIELD_NAMES


def _is_sla_field(field: dict[str, Any]) -> bool:
    schema = field.get("schema") or {}
    return (
        schema.get("custom") == _SLA_SCHEMA_KEY
        or schema.get("type") == _SLA_SCHEMA_TYPE
    )


def extract_request_type(value: Any) -> str | None:
    """Name of the request type of a Service Management request."""
    if value is None:
        return None

    request_type = _attribute_or_key(value, "requestType")
    if request_type is not None:
        name = _attribute_or_key(request_type, "name")
        if isinstance(name, str) and name:
            return name

    for key in ("name", "value"):
        name = _attribute_or_key(value, key)
        if isinstance(name, str) and name:
            return name

    return None


def extract_sla_state(value: Any) -> str | None:
    """State of one SLA of a Service Management request.

    Returns `ongoing` or `breached` while the clock runs, `met` or `breached`
    after the last cycle completes, and None if the request has no SLA data.
    """
    if value is None:
        return None

    ongoing_cycle = _attribute_or_key(value, "ongoingCycle")
    if ongoing_cycle is not None:
        if _attribute_or_key(ongoing_cycle, "breached"):
            return _SLA_STATE_BREACHED
        return _SLA_STATE_ONGOING

    completed_cycles = _attribute_or_key(value, "completedCycles")
    if completed_cycles:
        last_cycle = completed_cycles[-1]
        if _attribute_or_key(last_cycle, "breached"):
            return _SLA_STATE_BREACHED
        return _SLA_STATE_MET

    return None


def sla_metadata_key(field_name: str) -> str:
    normalized = "_".join(field_name.strip().lower().split())
    return f"{_SLA_METADATA_PREFIX}{normalized}"


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self._jsm_field_ids: JsmFieldIds | None = None
        self._service_desk_project_keys: list[str] | None = None

    @property
    @override
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _build_document_id(self, issue_key: str) -> str:
        return f"{DOC_ID_PREFIX}{super()._build_document_id(issue_key)}"

    @override
    def _process_issue(
        self, issue: Issue, parent_hierarchy_raw_node_id: str | None
    ) -> Document | None:
        document = super()._process_issue(
            issue=issue,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        )
        if document is None:
            return None

        document.id = self._build_document_id(issue.key)
        document.source = self.document_source
        document.metadata.update(self._request_metadata(issue))
        return document

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        jql = super()._get_jql_query(start, end)
        if self.jira_project:
            # validate_connector_settings checks that the project is a service desk.
            return jql

        # Keep the query inside the visible service desk projects. A custom JQL
        # query can match software project issues, and those are not requests.
        projects = ", ".join(
            f'"{project_key}"' for project_key in self._get_service_desk_project_keys()
        )
        return f"project in ({projects}) AND {jql}"

    @override
    def validate_connector_settings(self) -> None:
        super().validate_connector_settings()

        if not self.jira_project:
            # Resolve the scope now, so a connector that has no service desk
            # project fails validation instead of its first indexing run.
            self._get_service_desk_project_keys()
            return

        project = self.jira_client.project(self.jira_project)
        project_type = _attribute_or_key(project, "projectTypeKey")
        if project_type is not None and project_type != SERVICE_DESK_PROJECT_TYPE:
            raise ConnectorValidationError(
                f"Jira project {self.jira_project} is not a Jira Service Management "
                f"project (project type: {project_type})."
            )

    def _get_service_desk_project_keys(self) -> list[str]:
        """Keys of the service desk projects that the credentials can see.

        Raises ConnectorValidationError if the credentials see no service desk
        project, because then the connector has nothing to index.
        """
        if self._service_desk_project_keys is None:
            projects = self.jira_client.projects()
            self._service_desk_project_keys = [
                str(_attribute_or_key(project, "key"))
                for project in projects
                if _attribute_or_key(project, "projectTypeKey")
                == SERVICE_DESK_PROJECT_TYPE
                and _attribute_or_key(project, "key")
            ]

        if not self._service_desk_project_keys:
            raise ConnectorValidationError(
                "No Jira Service Management projects are visible to these credentials."
            )

        return self._service_desk_project_keys

    def _get_jsm_field_ids(self) -> JsmFieldIds:
        """Resolve the ids of the Service Management fields once per run."""
        if self._jsm_field_ids is not None:
            return self._jsm_field_ids

        try:
            fields: list[dict[str, Any]] = self.jira_client.fields()
        except Exception as e:
            logger.warning("Failed to fetch Jira fields: %s", e)
            self._jsm_field_ids = JsmFieldIds(request_type=None, slas={})
            return self._jsm_field_ids

        request_type_field_id: str | None = None
        sla_field_ids: dict[str, str] = {}
        for field in fields:
            field_id = field.get("id")
            if not field_id:
                continue
            if _is_sla_field(field):
                sla_field_ids[field_id] = field.get("name") or field_id
            elif request_type_field_id is None and _is_request_type_field(field):
                request_type_field_id = field_id

        self._jsm_field_ids = JsmFieldIds(
            request_type=request_type_field_id, slas=sla_field_ids
        )
        return self._jsm_field_ids

    def _request_metadata(self, issue: Issue) -> dict[str, str]:
        field_ids = self._get_jsm_field_ids()
        metadata: dict[str, str] = {}

        if field_ids.request_type:
            request_type = extract_request_type(
                best_effort_get_field_from_issue(issue, field_ids.request_type)
            )
            if request_type:
                metadata[_REQUEST_TYPE_METADATA_KEY] = request_type

        for field_id, field_name in field_ids.slas.items():
            sla_state = extract_sla_state(
                best_effort_get_field_from_issue(issue, field_id)
            )
            if sla_state:
                metadata[sla_metadata_key(field_name)] = sla_state

        return metadata


if __name__ == "__main__":
    import os

    from tests.daily.connectors.utils import load_all_from_connector

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JIRA_PROJECT_KEY"),
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    for doc in load_all_from_connector(
        connector=connector,
        start=0,
        end=datetime.now().timestamp(),
    ).documents:
        print(doc)
