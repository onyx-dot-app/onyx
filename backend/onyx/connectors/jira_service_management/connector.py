from datetime import datetime
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraIssue,
    _perform_jql_search,
    build_jql_query,
    process_jira_issue,
    scope_jql,
)
from onyx.connectors.jira.source_operations import is_cloud_gateway
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

SERVICE_DESK_PROJECT_TYPE = "service_desk"
_CLOUD_DEFAULT_JSM_SCOPE = f'projectType = "{SERVICE_DESK_PROJECT_TYPE}"'


def scope_jsm_jql(
    *,
    project_key: str | None,
    jql_query: str | None,
    clause: str,
    default_scope_clause: str = _CLOUD_DEFAULT_JSM_SCOPE,
) -> str:
    """JQL that limits ``clause`` to the configured JSM project, custom JQL query,
    or all Jira Service Management projects.
    """
    return scope_jql(
        project_key=project_key,
        jql_query=jql_query,
        clause=clause,
        default_scope_clause=default_scope_clause,
    )


def build_jsm_jql_query(
    *,
    project_key: str | None,
    jql_query: str | None,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    default_scope_clause: str = _CLOUD_DEFAULT_JSM_SCOPE,
) -> str:
    """JQL for Jira Service Management tickets within the poll window."""
    return build_jql_query(
        project_key=project_key,
        jql_query=jql_query,
        start=start,
        end=end,
        default_scope_clause=default_scope_clause,
    )


def extract_jsm_metadata(issue: JiraIssue) -> dict[str, str | list[str]]:
    """Extracts Jira Service Management specific metadata from an issue's fields
    (Customer Request Type, Service Desk ID, Organizations, Request Participants, and SLA status).
    """
    fields: Any = issue.get("fields")
    if not isinstance(fields, dict):
        return {}

    jsm_meta: dict[str, str | list[str]] = {}
    sla_seen = False
    sla_breached = False

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

            # JSM SLA field object contains `ongoingCycle` or `completedCycles`.
            # A ticket can have multiple SLA fields; mark breached if any SLA is breached.
            ongoing_cycle = field_value.get("ongoingCycle")
            if isinstance(ongoing_cycle, dict) and "breached" in ongoing_cycle:
                sla_seen = True
                sla_breached = sla_breached or bool(ongoing_cycle.get("breached"))
            elif isinstance(field_value.get("completedCycles"), list):
                cycles = field_value["completedCycles"]
                if cycles and isinstance(cycles[-1], dict) and "breached" in cycles[-1]:
                    sla_seen = True
                    sla_breached = sla_breached or bool(cycles[-1].get("breached"))

        elif isinstance(field_value, list) and field_value:
            # JSM Organizations or Request Participants lists
            first_elem = field_value[0]
            if isinstance(first_elem, dict):
                if (
                    "_links" in first_elem
                    and "name" in first_elem
                    and "id" in first_elem
                ):
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

    if sla_seen:
        jsm_meta["sla_breached"] = str(sla_breached)

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
    source_type: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT

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
        self._service_desk_project_keys: list[str] | None = None

    def _resolve_service_desk_project_keys(self) -> list[str]:
        if self._service_desk_project_keys is None:
            try:
                projects = self.source_operations.list_projects()
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
                raise

            resolved_keys: list[str] = []
            for p in projects:
                if not isinstance(p, dict) or not p.get("key"):
                    continue
                key = str(p["key"])
                project_type = p.get("projectTypeKey")
                if project_type is None:
                    try:
                        detail = self.source_operations.get_project(project_key=key)
                        project_type = (
                            detail.get("projectTypeKey")
                            if isinstance(detail, dict)
                            else None
                        )
                    except Exception as e:
                        self._handle_jira_connector_settings_error(e)
                        raise
                if project_type == SERVICE_DESK_PROJECT_TYPE:
                    resolved_keys.append(key)
            self._service_desk_project_keys = resolved_keys

        if not self._service_desk_project_keys:
            raise ConnectorValidationError(
                "No Jira Service Management (service_desk) projects found on this Jira instance."
            )
        return self._service_desk_project_keys

    def _get_default_scope_clause(self) -> str:
        """Returns the default JQL scope clause when neither ``project_key`` nor
        ``jql_query`` is set.

        Jira Cloud supports ``projectType = "service_desk"`` directly in JQL.
        Jira Server / Data Center does not support the ``projectType`` JQL field,
        so we resolve Service Desk project keys through the Projects REST API.
        """
        if self._source_operations is None or is_cloud_gateway(self.source_operations):
            return _CLOUD_DEFAULT_JSM_SCOPE

        quoted_keys = ", ".join(
            f'"{k}"' for k in self._resolve_service_desk_project_keys()
        )
        return f"project in ({quoted_keys})"

    @override
    def _fetch_issues_by_key(
        self, issue_keys: list[str]
    ) -> tuple[list[JiraIssue], dict[str, Exception]]:
        if not self.jira_project and not self.jql_query:
            self._get_default_scope_clause()
        return super()._fetch_issues_by_key(issue_keys)

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        default_clause = (
            _CLOUD_DEFAULT_JSM_SCOPE
            if (self.jira_project or self.jql_query)
            else self._get_default_scope_clause()
        )
        return build_jsm_jql_query(
            project_key=self.jira_project,
            jql_query=self.jql_query,
            start=start,
            end=end,
            default_scope_clause=default_clause,
        )

    @override
    def _search_issues_by_key(self, issue_keys: list[str]) -> list[JiraIssue]:
        keys_jql: str = "key in (%s)" % ", ".join(f'"{key}"' for key in issue_keys)
        default_clause = (
            _CLOUD_DEFAULT_JSM_SCOPE
            if (self.jira_project or self.jql_query)
            else self._get_default_scope_clause()
        )
        return list(
            self._search_all_issues(
                scope_jsm_jql(
                    project_key=self.jira_project,
                    jql_query=self.jql_query,
                    clause=keys_jql,
                    default_scope_clause=default_clause,
                )
            )
        )

    @override
    def _process_issue(
        self,
        issue: JiraIssue,
        parent_hierarchy_raw_node_id: str | None,
    ) -> Document | None:
        return process_jsm_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        )

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
            if project_type != SERVICE_DESK_PROJECT_TYPE:
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' has projectTypeKey '{project_type}', "
                    f"expected '{SERVICE_DESK_PROJECT_TYPE}' for Jira Service Management."
                )
        else:
            if is_cloud_gateway(self.source_operations):
                try:
                    self.source_operations.list_projects()
                except Exception as e:
                    self._handle_jira_connector_settings_error(e)
            else:
                self._resolve_service_desk_project_keys()


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
