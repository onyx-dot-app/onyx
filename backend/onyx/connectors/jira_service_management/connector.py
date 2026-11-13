"""Jira Service Management connector.

Service desk requests are Jira issues. This connector reuses the Jira
checkpoint and prune paths, and limits them to service desk projects. It adds
the request type, customer status, organizations, participants, SLA state, and
public versus internal comments.

Permission sync is not registered. The Jira permission jobs live in the
Enterprise Edition tree, which this connector does not change.
"""

import re
from collections.abc import Generator
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput, SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import (
    _RUN_FAILING_STATUS_CODES,
    JiraConnector,
    JiraConnectorCheckpoint,
    JiraIssue,
    _perform_jql_search,
)
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
    is_cloud_gateway,
)
from onyx.connectors.jira.utils import get_issue_field
from onyx.connectors.jira_service_management.config import (
    BLANK_JQL_ERROR,
    BLANK_PROJECT_KEY_ERROR,
    PROJECT_KEY_ERROR,
    PROJECT_KEY_RE,
)
from onyx.connectors.jira_service_management.fields import (
    SERVICE_DESK_PROJECT_TYPE,
    apply_service_desk_fields,
    field_custom_by_id,
    project_type_key,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ISSUE_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]+")
_COMMENT_PAGE_SIZE = 100
_NO_SERVICE_DESK_ERROR = (
    "No Jira Service Management projects are visible to this account."
)


def _normalize_project_key(project_key: str | None) -> str | None:
    """Return the project key in upper case.

    ``None`` means the connector does not limit by project. A blank string is
    a project scope with no key, so it is rejected.
    """
    if project_key is None:
        return None
    key = project_key.strip().upper()
    if not key:
        raise ConnectorValidationError(BLANK_PROJECT_KEY_ERROR)
    if PROJECT_KEY_RE.fullmatch(key) is None:
        raise ConnectorValidationError(PROJECT_KEY_ERROR)
    return key


def _normalize_jql(jql_query: str | None) -> str | None:
    """Return the JQL query with surrounding space removed.

    ``None`` means the connector does not use a JQL scope. A blank string is
    a JQL scope with no query, so it is rejected.
    """
    if jql_query is None:
        return None
    query = jql_query.strip()
    if not query:
        raise ConnectorValidationError(BLANK_JQL_ERROR)
    return query


class JiraServiceManagementConnector(JiraConnector):
    """Indexes Jira Service Management requests for one project, a JQL query,
    or every service desk the account can read."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # Skip a request that carries one of these labels.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=_normalize_project_key(project_key),
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=_normalize_jql(jql_query),
            scoped_token=scoped_token,
        )
        self._field_catalog: dict[str, str] | None = None
        self._service_desk_keys: list[str] | None = None

    @override
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
        self._field_catalog = None
        self._service_desk_keys = None
        return None

    def _service_desk_project_keys(self) -> list[str]:
        """Service desk project keys visible to the account.

        Server and Data Center have no ``projectType`` JQL field, so the
        connector names the projects instead.
        """
        if self._service_desk_keys is not None:
            return self._service_desk_keys
        keys: list[str] = []
        for project in self.source_operations.list_projects():
            if not isinstance(project, dict):
                continue
            key = project.get("key")
            if not isinstance(key, str) or not key:
                continue
            type_key = project_type_key(project)
            if type_key is None:
                type_key = self._fetched_project_type(key)
            if type_key == SERVICE_DESK_PROJECT_TYPE:
                keys.append(key)
        self._service_desk_keys = keys
        return keys

    def _fetched_project_type(self, project_key: str) -> str | None:
        """The project type from the project record, or None when it cannot be read."""
        try:
            project = self.source_operations.get_project(project_key=project_key)
        except JiraApiError as error:
            if error.status_code in _RUN_FAILING_STATUS_CODES:
                raise
            logger.warning(
                "Could not read project %s while looking for service desks: %s",
                project_key,
                error,
            )
            return None
        if not isinstance(project, dict):
            return None
        return project_type_key(project)

    def _service_desk_clause(self) -> str:
        """JQL that keeps the search inside service desk projects."""
        if is_cloud_gateway(self.source_operations):
            return "projectType = service_desk"
        keys = self._service_desk_project_keys()
        if not keys:
            raise ConnectorValidationError(_NO_SERVICE_DESK_ERROR)
        quoted = ", ".join(f'"{key}"' for key in keys)
        return f"project IN ({quoted})"

    def _user_scope(self) -> str | None:
        """The admin's project or JQL limit. A JQL query replaces the project."""
        if self.jql_query:
            return f"({self.jql_query})"
        if self.jira_project:
            return f'project = "{self.jira_project}"'
        return None

    def _scoped_jql(self, clause: str) -> str:
        """``clause`` plus the service desk limit and the admin's scope."""
        parts = [f"({clause})", f"({self._service_desk_clause()})"]
        user_scope = self._user_scope()
        if user_scope is not None:
            parts.append(user_scope)
        return " AND ".join(parts)

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        return self._scoped_jql(time_jql)

    @override
    def _search_issues_by_key(self, issue_keys: list[str]) -> list[JiraIssue]:
        keys_jql = "key in (%s)" % ", ".join(f'"{key}"' for key in issue_keys)
        return list(self._search_all_issues(self._scoped_jql(keys_jql)))

    def _field_custom_by_id(self) -> dict[str, str]:
        """Field id to Service Management schema key. Empty when the catalog fails."""
        if self._field_catalog is not None:
            return self._field_catalog
        try:
            fields = self.source_operations.list_fields()
        except JiraApiError as error:
            if error.status_code in _RUN_FAILING_STATUS_CODES:
                raise
            logger.warning(
                "Jira Service Management field catalog is unavailable: %s", error
            )
            self._field_catalog = {}
            return self._field_catalog
        except RuntimeError as error:
            # list_fields raises this for a payload that is not a list of
            # objects. The catalog only adds metadata, so the index continues.
            logger.warning(
                "Jira Service Management field catalog is malformed: %s", error
            )
            self._field_catalog = {}
            return self._field_catalog
        self._field_catalog = field_custom_by_id(fields)
        return self._field_catalog

    def _embedded_comments(
        self, issue: JiraIssue
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Comments already on the issue, and the reported total when Jira sent one."""
        comment_field = get_issue_field(issue, "comment")
        if not isinstance(comment_field, dict):
            return [], None
        raw_comments = comment_field.get("comments")
        comments = (
            [comment for comment in raw_comments if isinstance(comment, dict)]
            if isinstance(raw_comments, list)
            else []
        )
        total = comment_field.get("total")
        return comments, total if isinstance(total, int) else None

    def _fetch_comment_page(
        self, issue_key: str, start_at: int
    ) -> dict[str, Any] | None:
        """One comment page, or None when that page cannot be read."""
        try:
            page = self.source_operations.list_issue_comments(
                issue_key=issue_key,
                start_at=start_at,
                max_results=_COMMENT_PAGE_SIZE,
            )
        except JiraApiError as error:
            if error.status_code in _RUN_FAILING_STATUS_CODES:
                raise
            logger.warning(
                "Comment page failed for %s. Using the comments on the issue: %s",
                issue_key,
                error,
            )
            return None
        if not isinstance(page, dict):
            return None
        return page

    def _paged_comments(
        self, issue_key: str, total: int
    ) -> list[dict[str, Any]] | None:
        """Every comment on the issue, or None when a page cannot be read."""
        if _ISSUE_KEY_RE.fullmatch(issue_key) is None:
            return None
        comments: list[dict[str, Any]] = []
        start_at = 0
        # A short page is not the end. Jira can cap the page below the
        # requested size while ``total`` still has more comments.
        while start_at < total:
            page = self._fetch_comment_page(issue_key, start_at)
            if page is None:
                return None
            batch = page.get("comments")
            if not isinstance(batch, list) or not batch:
                break
            comments.extend(comment for comment in batch if isinstance(comment, dict))
            start_at += len(batch)
            page_total = page.get("total")
            if isinstance(page_total, int):
                total = page_total
        return comments

    def _issue_comments(self, issue: JiraIssue) -> list[dict[str, Any]]:
        """Every comment on the issue. Uses the embedded list when it is complete."""
        embedded, total = self._embedded_comments(issue)
        if total is None or total <= len(embedded):
            return embedded
        issue_key = issue.get("key")
        if not isinstance(issue_key, str):
            return embedded
        paged = self._paged_comments(issue_key, total)
        return embedded if paged is None else paged

    @override
    def _issue_to_items(
        self,
        issue: JiraIssue,
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        for item in super()._issue_to_items(
            issue, seen_hierarchy_node_ids, include_permissions
        ):
            if isinstance(item, Document):
                apply_service_desk_fields(
                    item,
                    issue,
                    jira_base_url=self.jira_base,
                    catalog=self._field_custom_by_id(),
                    comments=self._issue_comments(issue),
                    comment_email_blacklist=tuple(self.comment_email_blacklist),
                )
            yield item

    @override
    def _load_from_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        # A dead credential fails the run here, before any document is yielded.
        self._field_custom_by_id()
        return (
            yield from super()._load_from_checkpoint(
                jql, checkpoint, include_permissions
            )
        )

    def _assert_service_desk_project(self, project_key: str) -> None:
        """Raise when ``project_key`` is not a visible service desk project."""
        try:
            project = self.source_operations.get_project(project_key=project_key)
        except Exception as error:
            self._handle_jira_connector_settings_error(error)
            raise
        if not isinstance(project, dict) or (
            project_type_key(project) != SERVICE_DESK_PROJECT_TYPE
        ):
            raise ConnectorValidationError(
                f"Project {project_key} is not a Jira Service Management project."
            )

    def _assert_visible_service_desk(self) -> None:
        """Raise when the account cannot read any service desk project."""
        if is_cloud_gateway(self.source_operations):
            try:
                projects = self.source_operations.list_projects()
            except Exception as error:
                self._handle_jira_connector_settings_error(error)
                raise
            visible = any(
                isinstance(project, dict)
                and project_type_key(project) == SERVICE_DESK_PROJECT_TYPE
                for project in projects
            )
            if not visible:
                raise ConnectorValidationError(_NO_SERVICE_DESK_ERROR)
            # ``projectType`` is Cloud JQL. Run it once so a rejected clause
            # fails here, before the first index.
            self._validate_jql()
            return
        try:
            keys = self._service_desk_project_keys()
        except Exception as error:
            self._handle_jira_connector_settings_error(error)
            raise
        if not keys:
            raise ConnectorValidationError(_NO_SERVICE_DESK_ERROR)

    @override
    def validate_connector_settings(self) -> None:
        """Check the credential and the chosen scope before the first index."""
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        if self.jql_query:
            self._validate_jql()
            return
        if self.jira_project:
            self._assert_service_desk_project(self.jira_project)
            return
        self._assert_visible_service_desk()

    def _validate_jql(self) -> None:
        """Run the scoped query once so Jira rejects a bad clause here."""
        try:
            next(
                iter(
                    _perform_jql_search(
                        source_operations=self.source_operations,
                        jql=self._scoped_jql("updated >= 0"),
                        start=0,
                        max_results=1,
                        all_issue_ids=[],
                    )
                ),
                None,
            )
        except ConnectorValidationError:
            raise
        except Exception as error:
            self._handle_jira_connector_settings_error(error)
