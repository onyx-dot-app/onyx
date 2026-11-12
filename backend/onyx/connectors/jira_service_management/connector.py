"""The Jira Service Management connector.

A service desk is a Jira project and a request is a Jira issue. This connector
therefore subclasses ``JiraConnector``: paging, checkpointing, permission sync,
slim listing, retries and the ADF-to-text conversion are inherited, not copied.
It changes three things:

1. It talks through its own source-operations gateway, so the servicedeskapi
   calls and the Jira calls share one client and one credential.
2. Each request gains its service desk and request type in the text and the
   metadata, so search can answer "which portal raised this" and "which request
   type is this".
3. Documents report the JSM source.

The service desk metadata comes from the servicedeskapi, which needs a Service
Desk agent licence. When that fails the request is still indexed; the metadata
is skipped and the reason is logged once per run.
"""

from collections.abc import Generator
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, build_jql_query
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
    JsmApiError,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FIELD_PROJECT = "project"
# JSM stores the request type in a custom field whose id differs per site, so
# this reads the value that holds a ``requestType`` reference.
_REQUEST_TYPE_MARKER = "requestType"


def _request_type_id(issue: dict[str, Any]) -> str | None:
    """The request type id of a service desk request, or None."""
    raw_fields: Any = issue.get("fields")
    if not isinstance(raw_fields, dict):
        return None
    for value in raw_fields.values():
        if isinstance(value, dict) and _REQUEST_TYPE_MARKER in value:
            request_type: Any = value[_REQUEST_TYPE_MARKER]
            if isinstance(request_type, dict):
                request_type_id: Any = request_type.get("id")
                if isinstance(request_type_id, str) and request_type_id:
                    return request_type_id
    return None


class JiraServiceManagementConnector(JiraConnector):
    """Indexes the requests of one service desk project."""

    # The parent attributes the Jira gateway; this connector builds the JSM
    # gateway, which serves the same credential and adds the servicedeskapi
    # operations.
    _source_operations: JiraServiceManagementSourceOperations | None

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        include_service_desk_metadata: bool = True,
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
        self.include_service_desk_metadata = include_service_desk_metadata
        self._service_desk_metadata: dict[str, Any] | None = None
        self._metadata_unavailable_reason: str | None = None
        self._logged_metadata_failure = False

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """The sync query, always limited to this service desk.

        The inherited implementation lets a custom JQL *replace* the project
        predicate, so ``status = Open`` would index other projects. This
        connector is defined as one service desk, so the project predicate is
        always present and the custom JQL can only narrow within it.

        The parent wraps this query in parentheses and appends a time filter,
        so the result must remain a plain conjunction.
        """
        scoped = f'project = "{self.jira_project}"' if self.jira_project else ""
        if self.jql_query:
            scoped = (
                f"{scoped} AND ({self.jql_query})" if scoped else f"({self.jql_query})"
            )
        return build_jql_query(project_key=None, jql_query=scoped, start=start, end=end)

    @property
    def source_operations(self) -> JiraServiceManagementSourceOperations:
        """The JSM gateway. The parent attributes its gateway to
        ``JiraSourceOperations``; this connector builds the JSM one, so the
        type is narrowed here."""
        operations = self._source_operations
        if operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return operations

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Wires this connector to the JSM gateway instead of the Jira one, so
        the servicedeskapi operations share the credential and the client."""
        self._source_operations = JiraServiceManagementSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
            ),
            connector_specific_config={
                "jira_base_url": self.jira_base,
                "scoped_token": self.scoped_token,
            },
        )
        return None

    def _load_service_desk_metadata(self) -> dict[str, Any] | None:
        """The service desk of this project, or None with the reason stored.

        One call per run; the result is cached. A licence or permission problem
        is not fatal: requests stay indexable through the Jira API.
        """
        if self._service_desk_metadata is not None:
            return self._service_desk_metadata
        if self._metadata_unavailable_reason is not None:
            return None
        try:
            desk = self.source_operations.get_service_desk(
                project_key=self.jira_project or ""
            )
        except JsmApiError as e:
            self._metadata_unavailable_reason = (
                f"status {e.status_code}" if e.status_code else str(e)
            )
            return None
        if not desk.get("id"):
            self._metadata_unavailable_reason = "the site returned no service desk id"
            return None
        self._service_desk_metadata = desk
        return desk

    def _request_type_name(self, issue: dict[str, Any]) -> str | None:
        request_type_id = _request_type_id(issue)
        desk = self._service_desk_metadata
        if not request_type_id or not desk or not desk.get("id"):
            return None
        try:
            request_type = self.source_operations.get_request_type(
                service_desk_id=str(desk["id"]),
                request_type_id=request_type_id,
            )
        except JsmApiError:
            return None
        name: Any = request_type.get("name")
        return name if isinstance(name, str) and name else None

    def _apply_service_desk_metadata(
        self, issue: dict[str, Any], document: Document
    ) -> None:
        """Adds the service desk and request type to a built document."""
        if not self.include_service_desk_metadata:
            return
        desk = self._load_service_desk_metadata()
        if desk is None:
            if not self._logged_metadata_failure:
                self._logged_metadata_failure = True
                logger.info(
                    "JSM service desk metadata is unavailable (%s). Indexing "
                    "requests without it. A Service Desk agent licence supplies "
                    "the portal name and the request type.",
                    self._metadata_unavailable_reason,
                )
            return

        lines: list[str] = []
        desk_name: Any = desk.get("projectName")
        if isinstance(desk_name, str) and desk_name:
            lines.append(f"Service desk: {desk_name}")
            document.metadata["service_desk"] = desk_name
        request_type = self._request_type_name(issue)
        if request_type:
            lines.append(f"Request type: {request_type}")
            document.metadata["request_type"] = request_type
        if (
            lines
            and document.sections
            and isinstance(document.sections[0], TextSection)
        ):
            section = document.sections[0]
            section.text = "\n".join(lines) + "\n" + section.text

        # Requests belong to the JSM source, not to plain Jira, so a scope
        # filter on either source still finds them.
        document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _issue_to_items(
        self,
        issue: dict[str, Any],
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        """The inherited Jira items of this issue, enriched when a document is
        yielded."""
        for item in super()._issue_to_items(
            issue, seen_hierarchy_node_ids, include_permissions
        ):
            if isinstance(item, Document):
                self._apply_service_desk_metadata(issue, item)
            yield item
