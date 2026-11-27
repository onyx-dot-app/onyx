from collections.abc import Generator
from typing import Any, overload

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraConnectorCheckpoint,
    JiraIssue,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

SERVICE_DESK_PROJECT_TYPE = "service_desk"
DOCUMENT_ID_PREFIX = "jira_service_management:"

REQUEST_TYPE_KEY = "request_type"
REQUEST_STATUS_KEY = "request_status"
PORTAL_LINK_KEY = "portal_link"

_REQUEST_TYPE_FIELD = "requestType"
_CURRENT_STATUS_FIELD = "currentStatus"


def _request_field(issue: JiraIssue) -> dict[str, Any] | None:
    """The "Customer Request Type" field of a request. Its custom field id
    differs per site, so find it by shape."""
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    for value in fields.values():
        if isinstance(value, dict) and isinstance(value.get(_REQUEST_TYPE_FIELD), dict):
            return value
    return None


def request_metadata(issue: JiraIssue) -> dict[str, str]:
    """The portal facts of a request: request type, portal status and link."""
    field: dict[str, Any] | None = _request_field(issue)
    if field is None:
        return {}
    metadata: dict[str, str] = {}
    request_type: Any = field[_REQUEST_TYPE_FIELD].get("name")
    if isinstance(request_type, str) and request_type:
        metadata[REQUEST_TYPE_KEY] = request_type
    current_status: Any = field.get(_CURRENT_STATUS_FIELD)
    if isinstance(current_status, dict):
        status: Any = current_status.get("status")
        if isinstance(status, str) and status:
            metadata[REQUEST_STATUS_KEY] = status
    links: Any = field.get("_links")
    if isinstance(links, dict):
        portal_link: Any = links.get("web")
        if isinstance(portal_link, str) and portal_link:
            metadata[PORTAL_LINK_KEY] = portal_link
    return metadata


def _without_internal_comments(issue: JiraIssue) -> JiraIssue:
    """A copy of the issue without agent-only comments (`jsdPublic` is false).
    The input is not changed."""
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return issue
    comment: Any = fields.get("comment")
    if not isinstance(comment, dict):
        return issue
    comments: Any = comment.get("comments")
    if not isinstance(comments, list):
        return issue
    public_comments = [
        c for c in comments if not (isinstance(c, dict) and c.get("jsdPublic") is False)
    ]
    filtered: JiraIssue = {
        **issue,
        "fields": {**fields, "comment": {**comment, "comments": public_comments}},
    }
    return filtered


@overload
def _namespaced(item: Document) -> Document: ...
@overload
def _namespaced(item: ConnectorFailure) -> ConnectorFailure: ...
@overload
def _namespaced(item: SlimDocument | HierarchyNode) -> SlimDocument | HierarchyNode: ...
@overload
def _namespaced(
    item: Document | ConnectorFailure | HierarchyNode,
) -> Document | ConnectorFailure | HierarchyNode: ...
def _namespaced(
    item: Document | ConnectorFailure | SlimDocument | HierarchyNode,
) -> Document | ConnectorFailure | SlimDocument | HierarchyNode:
    """Prefix the document ID, so a request does not collide with the same issue
    indexed by the Jira connector. The Jira code keeps the plain IDs."""
    if isinstance(item, Document | SlimDocument):
        item.id = DOCUMENT_ID_PREFIX + item.id
    elif isinstance(item, ConnectorFailure):
        document = item.failed_document
        if document is not None:
            item.failed_document = document.model_copy(
                update={"document_id": DOCUMENT_ID_PREFIX + document.document_id}
            )
    return item


def _stripped(failure: ConnectorFailure) -> ConnectorFailure:
    """A copy of the failure with the plain Jira document ID."""
    document = failure.failed_document
    if document is None or not document.document_id.startswith(DOCUMENT_ID_PREFIX):
        return failure
    plain_id = document.document_id.removeprefix(DOCUMENT_ID_PREFIX)
    return failure.model_copy(
        update={
            "failed_document": document.model_copy(update={"document_id": plain_id})
        }
    )


class JiraServiceManagementConnector(JiraConnector):
    """Indexes the requests of one Jira Service Management project. Requests
    are Jira issues, so the Jira connector does the fetching."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        if not project_key.strip():
            raise ValueError("A Jira Service Management project key is required.")
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            scoped_token=scoped_token,
        )

    def _issue_to_items(
        self,
        issue: JiraIssue,
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        for item in super()._issue_to_items(
            _without_internal_comments(issue),
            seen_hierarchy_node_ids,
            include_permissions,
        ):
            if isinstance(item, Document):
                item.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
                item.metadata.update(request_metadata(issue))
            yield item

    @override
    def _load_from_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        output = super()._load_from_checkpoint(jql, checkpoint, include_permissions)
        while True:
            try:
                item = next(output)
            except StopIteration as stop:
                return stop.value
            yield _namespaced(item)

    @override
    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        stripped = [_stripped(failure) for failure in errors]
        for item in super().reindex(stripped, include_permissions):
            yield _namespaced(item)

    @override
    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        *,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        for batch in super()._retrieve_all_slim_docs(
            start=start,
            end=end,
            callback=callback,
            include_permissions=include_permissions,
        ):
            yield [_namespaced(item) for item in batch]

    def validate_connector_settings(self) -> None:
        if self._source_operations is None or self.jira_project is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            project: dict[str, Any] = self.source_operations.get_project(
                project_key=self.jira_project, fast=True
            )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            raise
        if project.get("projectTypeKey") != SERVICE_DESK_PROJECT_TYPE:
            raise ConnectorValidationError(
                f"Jira project {self.jira_project} is not a Jira Service "
                "Management project. Use the Jira connector for other project types."
            )
