from collections.abc import Generator
from datetime import datetime
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraConnectorCheckpoint,
    JiraIssue,
    _perform_jql_search,
    process_jira_issue,
)
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira.utils import get_issue_field
from onyx.connectors.models import Document, HierarchyNode
from onyx.utils.logger import setup_logger

logger = setup_logger()

SERVICE_DESK_PROJECT_TYPE = "service_desk"


def scope_jsm_jql(
    *, project_key: str | None, jql_query: str | None, clause: str
) -> str:
    """JQL that limits ``clause`` to the configured JSM project, custom JQL query,
    or all Jira Service Management projects (``projectType = "service_desk"``).
    """
    if jql_query:
        return f"({jql_query}) AND {clause}"
    if project_key:
        return f'project = "{project_key}" AND {clause}'
    return f'projectType = "{SERVICE_DESK_PROJECT_TYPE}" AND {clause}'


def build_jsm_jql_query(
    *,
    project_key: str | None,
    jql_query: str | None,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> str:
    """JQL for Jira Service Management tickets within the poll window."""
    time_jql: str = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
    return scope_jsm_jql(
        project_key=project_key, jql_query=jql_query, clause=time_jql
    )


def extract_jsm_metadata(issue: JiraIssue) -> dict[str, str | list[str]]:
    """Extracts Jira Service Management specific metadata from an issue's fields
    (Customer Request Type, Service Desk ID, Organizations, Request Participants, and SLA status).
    """
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return {}

    jsm_meta: dict[str, str | list[str]] = {}

    for field_value in fields.values():
        if isinstance(field_value, dict):
            # JSM Customer Request Type object contains `requestType` and/or `_links` + `serviceDeskId`
            req_type = field_value.get("requestType")
            if isinstance(req_type, dict):
                req_name = req_type.get("name")
                if isinstance(req_name, str) and req_name:
                    jsm_meta["request_type"] = req_name
                sd_id = req_type.get("serviceDeskId") or field_value.get(
                    "serviceDeskId"
                )
                if sd_id is not None:
                    jsm_meta["service_desk_id"] = str(sd_id)

            # JSM SLA field object contains `ongoingCycle` or `completedCycles`
            ongoing_cycle = field_value.get("ongoingCycle")
            if isinstance(ongoing_cycle, dict) and "breached" in ongoing_cycle:
                jsm_meta["sla_breached"] = str(bool(ongoing_cycle.get("breached")))
            elif isinstance(field_value.get("completedCycles"), list):
                cycles = field_value["completedCycles"]
                if cycles and isinstance(cycles[-1], dict) and "breached" in cycles[-1]:
                    jsm_meta["sla_breached"] = str(bool(cycles[-1].get("breached")))

        elif isinstance(field_value, list) and field_value:
            # JSM Organizations or Request Participants lists
            first_elem = field_value[0]
            if isinstance(first_elem, dict):
                if "_links" in first_elem and "name" in first_elem and "id" in first_elem:
                    org_names = [
                        str(org["name"])
                        for org in field_value
                        if isinstance(org, dict) and org.get("name")
                    ]
                    if org_names:
                        jsm_meta["organizations"] = org_names
                elif "emailAddress" in first_elem or "accountId" in first_elem:
                    participants = [
                        str(p.get("displayName") or p.get("emailAddress"))
                        for p in field_value
                        if isinstance(p, dict)
                        and (p.get("displayName") or p.get("emailAddress"))
                    ]
                    if participants and "request_participants" not in jsm_meta:
                        jsm_meta["request_participants"] = participants

    return jsm_meta


def process_jsm_issue(
    jira_base_url: str,
    issue: JiraIssue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    doc = process_jira_issue(
        jira_base_url=jira_base_url,
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
        labels_to_skip=labels_to_skip,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    if doc is None:
        return None

    doc.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    jsm_metadata = extract_jsm_metadata(issue)
    if jsm_metadata:
        doc.metadata.update(jsm_metadata)
    return doc


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
        return None

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        return build_jsm_jql_query(
            project_key=self.jira_project,
            jql_query=self.jql_query,
            start=start,
            end=end,
        )

    @override
    def _search_issues_by_key(self, issue_keys: list[str]) -> list[JiraIssue]:
        keys_jql: str = "key in (%s)" % ", ".join(f'"{key}"' for key in issue_keys)
        return list(
            self._search_all_issues(
                scope_jsm_jql(
                    project_key=self.jira_project,
                    jql_query=self.jql_query,
                    clause=keys_jql,
                )
            )
        )

    @override
    def _issue_to_items(
        self,
        issue: JiraIssue,
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        project = get_issue_field(issue, "project")
        project_key = project["key"] if project else None
        project_name = project.get("name") if project else None

        if project_key:
            yield from self._yield_project_hierarchy_node(
                project_key, project_name, seen_hierarchy_node_ids
            )
            parent = get_issue_field(issue, "parent")
            if parent:
                yield from self._yield_parent_hierarchy_node_if_epic(
                    parent, project_key, seen_hierarchy_node_ids
                )
            if self._is_epic(issue):
                yield from self._yield_epic_hierarchy_node(
                    issue, project_key, seen_hierarchy_node_ids
                )

        parent_hierarchy_raw_node_id = (
            self._get_parent_hierarchy_raw_node_id(issue, project_key)
            if project_key
            else None
        )

        if document := process_jsm_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        ):
            if include_permissions:
                document.external_access = self._get_project_permissions(
                    project_key,  # ty: ignore[invalid-argument-type]
                    add_prefix=True,
                )
            yield document

    @override
    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            super().validate_connector_settings()
            return

        if self.jql_query:
            try:
                next(
                    iter(
                        _perform_jql_search(
                            source_operations=self.source_operations,
                            jql=self.jql_query,
                            start=0,
                            max_results=1,
                            all_issue_ids=[],
                        )
                    ),
                    None,
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
        elif self.jira_project:
            try:
                project = self.source_operations.get_project(
                    project_key=self.jira_project
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
                return

            project_type = project.get("projectTypeKey")
            if (
                isinstance(project_type, str)
                and project_type
                and project_type != SERVICE_DESK_PROJECT_TYPE
            ):
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' has projectTypeKey '{project_type}', "
                    f"expected '{SERVICE_DESK_PROJECT_TYPE}' for Jira Service Management."
                )
        else:
            try:
                self.source_operations.list_projects()
            except Exception as e:
                self._handle_jira_connector_settings_error(e)


if __name__ == "__main__":
    import os

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JIRA_PROJECT_KEY"),
        comment_email_blacklist=[],
    )

    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    start = 0
    end = datetime.now().timestamp()

    for doc in load_all_from_connector(
        connector=connector,
        start=start,
        end=end,
    ).documents:
        print(doc)
