import copy
import json
import os
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

import requests
from jira import JIRA
from jira.exceptions import JIRAError
from jira.resources import Issue
from more_itertools import chunked
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()

ONE_HOUR = 3600

_MAX_RESULTS_FETCH_IDS = 5000
_JSM_FULL_PAGE_SIZE = 50

# Constants for Jira field names
_FIELD_REPORTER = "reporter"
_FIELD_ASSIGNEE = "assignee"
_FIELD_PRIORITY = "priority"
_FIELD_STATUS = "status"
_FIELD_RESOLUTION = "resolution"
_FIELD_LABELS = "labels"
_FIELD_KEY = "key"
_FIELD_CREATED = "created"
_FIELD_DUEDATE = "duedate"
_FIELD_ISSUETYPE = "issuetype"
_FIELD_PARENT = "parent"
_FIELD_ASSIGNEE_EMAIL = "assignee_email"
_FIELD_REPORTER_EMAIL = "reporter_email"
_FIELD_PROJECT = "project"
_FIELD_PROJECT_NAME = "project_name"
_FIELD_UPDATED = "updated"
_FIELD_RESOLUTION_DATE = "resolutiondate"
_FIELD_RESOLUTION_DATE_KEY = "resolution_date"

# JSM-specific field name constants
_FIELD_REQUEST_TYPE = "request_type"


def _is_cloud_client(jira_client: JIRA) -> bool:
    return jira_client._options["rest_api_version"] == JIRA_CLOUD_API_VERSION


def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
    all_issue_ids: list[list[str]] | None = None,
    checkpoint_callback: (
        Callable[[Iterator[list[str]], str | None], None] | None
    ) = None,
    nextPageToken: str | None = None,
    ids_done: bool = False,
) -> Iterable[Issue]:
    if _is_cloud_client(jira_client):
        if all_issue_ids is None:
            raise ValueError("all_issue_ids is required for v3")
        return _perform_jql_search_v3(
            jira_client,
            jql,
            max_results,
            all_issue_ids,
            fields=fields,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=nextPageToken,
            ids_done=ids_done,
        )
    else:
        return _perform_jql_search_v2(jira_client, jql, start, max_results, fields)


def _handle_jira_search_error(e: Exception, jql: str) -> None:
    error_text = ""
    status_code = None

    def _format_error_text(error_payload: Any) -> str:
        error_messages = (
            error_payload.get("errorMessages", [])
            if isinstance(error_payload, dict)
            else []
        )
        if error_messages:
            return (
                "; ".join(error_messages)
                if isinstance(error_messages, list)
                else str(error_messages)
            )
        return str(error_payload)

    if hasattr(e, "status_code"):
        status_code = e.status_code
        raw_text = getattr(e, "text", "")
        if isinstance(raw_text, str):
            try:
                error_text = _format_error_text(json.loads(raw_text))
            except Exception:
                error_text = raw_text
        else:
            error_text = str(raw_text)
    elif hasattr(e, "response") and e.response is not None:
        status_code = e.response.status_code
        try:
            error_json = e.response.json()
            error_text = _format_error_text(error_json)
        except Exception:
            error_text = e.response.text

    if status_code == 400:
        if "does not exist for the field 'project'" in error_text:
            raise ConnectorValidationError(
                f"The specified Jira project does not exist or you don't have access to it. JQL query: {jql}. Error: {error_text}"
            )
        raise ConnectorValidationError(
            f"Invalid JQL query. JQL: {jql}. Error: {error_text}"
        )
    elif status_code == 401:
        raise CredentialExpiredError(
            "Jira credentials are expired or invalid (HTTP 401)."
        )
    elif status_code == 403:
        raise InsufficientPermissionsError(
            f"Insufficient permissions to execute JQL query. JQL: {jql}"
        )

    raise e


def enhanced_search_ids(
    jira_client: JIRA, jql: str, nextPageToken: str | None = None
) -> tuple[list[str], str | None]:
    enhanced_search_path = jira_client._get_url("search/jql")
    params: dict[str, str | int | None] = {
        "jql": jql,
        "maxResults": _MAX_RESULTS_FETCH_IDS,
        "nextPageToken": nextPageToken,
        "fields": "id",
    }
    try:
        response = jira_client._session.get(enhanced_search_path, params=params)
        response.raise_for_status()
        response_json = response.json()
    except Exception as e:
        _handle_jira_search_error(e, jql)
        raise

    return [str(issue["id"]) for issue in response_json["issues"]], response_json.get(
        "nextPageToken"
    )


def _bulk_fetch_request(
    jira_client: JIRA, issue_ids: list[str], fields: str | None
) -> list[dict[str, Any]]:
    bulk_fetch_path = jira_client._get_url("issue/bulkfetch")
    payload: dict[str, Any] = {"issueIdsOrKeys": issue_ids}
    payload["fields"] = fields.split(",") if fields else ["*all"]

    resp = jira_client._session.post(bulk_fetch_path, json=payload)
    return resp.json()["issues"]


def bulk_fetch_issues(
    jira_client: JIRA, issue_ids: list[str], fields: str | None = None
) -> list[Issue]:
    try:
        raw_issues = _bulk_fetch_request(jira_client, issue_ids, fields)
    except requests.exceptions.JSONDecodeError:
        if len(issue_ids) <= 1:
            logger.exception(
                f"Jira bulk-fetch response for issue(s) {issue_ids} could not "
                f"be decoded as JSON (response too large or truncated)."
            )
            raise

        mid = len(issue_ids) // 2
        logger.warning(
            f"Jira bulk-fetch JSON decode failed for batch of {len(issue_ids)} issues. "
            f"Splitting into sub-batches of {mid} and {len(issue_ids) - mid}."
        )
        left = bulk_fetch_issues(jira_client, issue_ids[:mid], fields)
        right = bulk_fetch_issues(jira_client, issue_ids[mid:], fields)
        return left + right
    except Exception as e:
        logger.error(f"Error fetching issues: {e}")
        raise

    return [
        Issue(jira_client._options, jira_client._session, raw=issue)
        for issue in raw_issues
    ]


def _perform_jql_search_v3(
    jira_client: JIRA,
    jql: str,
    max_results: int,
    all_issue_ids: list[list[str]],
    fields: str | None = None,
    checkpoint_callback: (
        Callable[[Iterator[list[str]], str | None], None] | None
    ) = None,
    nextPageToken: str | None = None,
    ids_done: bool = False,
) -> Iterable[Issue]:
    if not ids_done:
        new_ids, pageToken = enhanced_search_ids(jira_client, jql, nextPageToken)
        if checkpoint_callback is not None:
            checkpoint_callback(chunked(new_ids, max_results), pageToken)

    if all_issue_ids:
        yield from bulk_fetch_issues(jira_client, all_issue_ids.pop(), fields)


def _perform_jql_search_v2(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
) -> Iterable[Issue]:
    logger.debug(
        f"Fetching JSM issues with JQL: {jql}, starting at {start}, max results: {max_results}"
    )
    try:
        issues = jira_client.search_issues(
            jql_str=jql,
            startAt=start,
            maxResults=max_results,
            fields=fields,
        )
    except JIRAError as e:
        _handle_jira_search_error(e, jql)
        raise

    for issue in issues:
        if isinstance(issue, Issue):
            yield issue
        else:
            raise RuntimeError(f"Found Jira object not of type Issue: {issue}")


def _get_jsm_request_type(jira_client: JIRA, issue: Issue) -> str | None:
    """Attempt to fetch the JSM request type for an issue.

    JSM Cloud stores this in a custom field (typically
    `issue.fields.customfield_10010`) which contains a
    ``requestType`` object with a ``name`` attribute.  For Jira
    Server / Data Center the field layout may differ, so we fall
    back gracefully.
    """
    # Cloud: the request type lives in the "Customer Request Type" custom field.
    request_type_field = best_effort_get_field_from_issue(issue, "customfield_10010")
    if request_type_field is not None:
        # Cloud returns an object with .requestType.name
        if hasattr(request_type_field, "requestType"):
            rt = request_type_field.requestType
            if hasattr(rt, "name"):
                return rt.name
        # Alternatively it might be a dict (raw API)
        if isinstance(request_type_field, dict):
            rt = request_type_field.get("requestType")
            if isinstance(rt, dict):
                return rt.get("name")
            # Sometimes the field itself contains the name directly
            name = request_type_field.get("name")
            if name:
                return name

    return None


def process_jsm_issue(
    jira_client: JIRA,
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    if labels_to_skip:
        if any(label in issue.fields.labels for label in labels_to_skip):
            logger.info(
                f"Skipping {issue.key} because it has a label to skip. Found "
                f"labels: {issue.fields.labels}. Labels to skip: {labels_to_skip}."
            )
            return None

    if isinstance(issue.fields.description, str):
        description = issue.fields.description
    else:
        description = extract_text_from_adf(issue.raw["fields"]["description"])

    comments = get_comment_strs(
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
    )
    ticket_content = f"{description}\n" + "\n".join(
        [f"Comment: {comment}" for comment in comments if comment]
    )

    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        logger.info(
            f"Skipping {issue.key} because it exceeds the maximum size of {JIRA_CONNECTOR_MAX_TICKET_SIZE} bytes."
        )
        return None

    page_url = build_jira_url(jira_base_url, issue.key)

    metadata_dict: dict[str, str | list[str]] = {}
    people = set()

    creator = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
    if creator is not None and (
        basic_expert_info := best_effort_basic_expert_info(creator)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_REPORTER] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_REPORTER_EMAIL] = email

    assignee = best_effort_get_field_from_issue(issue, _FIELD_ASSIGNEE)
    if assignee is not None and (
        basic_expert_info := best_effort_basic_expert_info(assignee)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_ASSIGNEE] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_ASSIGNEE_EMAIL] = email

    metadata_dict[_FIELD_KEY] = issue.key
    if priority := best_effort_get_field_from_issue(issue, _FIELD_PRIORITY):
        metadata_dict[_FIELD_PRIORITY] = priority.name
    if status := best_effort_get_field_from_issue(issue, _FIELD_STATUS):
        metadata_dict[_FIELD_STATUS] = status.name
    if resolution := best_effort_get_field_from_issue(issue, _FIELD_RESOLUTION):
        metadata_dict[_FIELD_RESOLUTION] = resolution.name
    if labels := best_effort_get_field_from_issue(issue, _FIELD_LABELS):
        metadata_dict[_FIELD_LABELS] = labels
    if created := best_effort_get_field_from_issue(issue, _FIELD_CREATED):
        metadata_dict[_FIELD_CREATED] = created
    if updated := best_effort_get_field_from_issue(issue, _FIELD_UPDATED):
        metadata_dict[_FIELD_UPDATED] = updated
    if duedate := best_effort_get_field_from_issue(issue, _FIELD_DUEDATE):
        metadata_dict[_FIELD_DUEDATE] = duedate
    if issuetype := best_effort_get_field_from_issue(issue, _FIELD_ISSUETYPE):
        metadata_dict[_FIELD_ISSUETYPE] = issuetype.name
    if resolutiondate := best_effort_get_field_from_issue(
        issue, _FIELD_RESOLUTION_DATE
    ):
        metadata_dict[_FIELD_RESOLUTION_DATE_KEY] = resolutiondate

    # JSM-specific: extract request type
    request_type = _get_jsm_request_type(jira_client, issue)
    if request_type:
        metadata_dict[_FIELD_REQUEST_TYPE] = request_type

    parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
    if parent is not None:
        metadata_dict[_FIELD_PARENT] = parent.key

    project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
    if project is not None:
        metadata_dict[_FIELD_PROJECT_NAME] = project.name
        metadata_dict[_FIELD_PROJECT] = project.key
    else:
        logger.error(f"Project should exist but does not for {issue.key}")

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )


class JsmConnectorCheckpoint(ConnectorCheckpoint):
    all_issue_ids: list[list[str]] = []
    ids_done: bool = False
    cursor: str | None = None
    offset: int | None = None
    seen_hierarchy_node_ids: list[str] = []


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JsmConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
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
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jql_query = jql_query
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
        self._project_permissions_cache: dict[str, Any] = {}

    @property
    def comment_email_blacklist(self) -> tuple:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    @property
    def quoted_jira_project(self) -> str:
        if not self.jira_project:
            return ""
        return f'"{self.jira_project}"'

    def _get_project_permissions(
        self, project_key: str, add_prefix: bool = False
    ) -> Any:
        cache_key = f"{project_key}:{'prefixed' if add_prefix else 'unprefixed'}"
        if cache_key not in self._project_permissions_cache:
            self._project_permissions_cache[cache_key] = get_project_permissions(
                jira_client=self.jira_client,
                jira_project=project_key,
                add_prefix=add_prefix,
            )
        return self._project_permissions_cache[cache_key]

    def _is_epic(self, issue: Issue) -> bool:
        issuetype = best_effort_get_field_from_issue(issue, _FIELD_ISSUETYPE)
        if issuetype is None:
            return False
        return issuetype.name.lower() == "epic"

    def _is_parent_epic(self, parent: Any) -> bool:
        parent_issuetype = (
            getattr(parent.fields, "issuetype", None)
            if hasattr(parent, "fields")
            else None
        )
        if parent_issuetype is None:
            return False
        return parent_issuetype.name.lower() == "epic"

    def _yield_project_hierarchy_node(
        self,
        project_key: str,
        project_name: str | None,
        seen_hierarchy_node_ids: set[str],
    ) -> Generator[HierarchyNode, None, None]:
        if project_key in seen_hierarchy_node_ids:
            return

        seen_hierarchy_node_ids.add(project_key)

        yield HierarchyNode(
            raw_node_id=project_key,
            raw_parent_id=None,
            display_name=project_name or project_key,
            link=f"{self.jira_base}/projects/{project_key}",
            node_type=HierarchyNodeType.PROJECT,
        )

    def _yield_epic_hierarchy_node(
        self,
        issue: Issue,
        project_key: str,
        seen_hierarchy_node_ids: set[str],
    ) -> Generator[HierarchyNode, None, None]:
        issue_key = issue.key
        if issue_key in seen_hierarchy_node_ids:
            return

        seen_hierarchy_node_ids.add(issue_key)

        yield HierarchyNode(
            raw_node_id=issue_key,
            raw_parent_id=project_key,
            display_name=f"{issue_key}: {issue.fields.summary}",
            link=build_jira_url(self.jira_base, issue_key),
            node_type=HierarchyNodeType.FOLDER,
        )

    def _yield_parent_hierarchy_node_if_epic(
        self,
        parent: Any,
        project_key: str,
        seen_hierarchy_node_ids: set[str],
    ) -> Generator[HierarchyNode, None, None]:
        parent_key = parent.key
        if parent_key in seen_hierarchy_node_ids:
            return

        if not self._is_parent_epic(parent):
            return

        seen_hierarchy_node_ids.add(parent_key)

        parent_summary = (
            getattr(parent.fields, "summary", None)
            if hasattr(parent, "fields")
            else None
        )
        display_name = (
            f"{parent_key}: {parent_summary}" if parent_summary else parent_key
        )

        yield HierarchyNode(
            raw_node_id=parent_key,
            raw_parent_id=project_key,
            display_name=display_name,
            link=build_jira_url(self.jira_base, parent_key),
            node_type=HierarchyNodeType.FOLDER,
        )

    def _get_parent_hierarchy_raw_node_id(self, issue: Issue, project_key: str) -> str:
        parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
        if parent is None:
            return project_key

        if self._is_parent_epic(parent):
            return parent.key

        return project_key

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def _is_service_management_project(self, project_key: str) -> bool:
        """Check if a project is a JSM (service management) project.

        JSM projects have projectTypeKey == "service_desk".
        """
        try:
            project = self.jira_client.project(project_key)
            project_type = getattr(project, "projectTypeKey", None)
            return project_type == "service_desk"
        except Exception:
            # If we can't determine, treat it as a JSM project to avoid blocking
            return True

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        if self.jira_project:
            base_jql = f"project = {self.quoted_jira_project}"
            return f"{base_jql} AND {time_jql}"

        return time_jql

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)
        try:
            return self._load_from_checkpoint(
                jql, checkpoint, include_permissions=False
            )
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return self._load_from_checkpoint(
                    jql, checkpoint, include_permissions=False
                )
            raise e

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)
        try:
            return self._load_from_checkpoint(jql, checkpoint, include_permissions=True)
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return self._load_from_checkpoint(
                    jql, checkpoint, include_permissions=True
                )
            raise e

    def _load_from_checkpoint(
        self, jql: str, checkpoint: JsmConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)

        seen_hierarchy_node_ids = set(new_checkpoint.seen_hierarchy_node_ids)

        checkpoint_callback = make_checkpoint_callback(new_checkpoint)

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JSM_FULL_PAGE_SIZE,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
                project_key = project.key if project else None
                project_name = project.name if project else None

                if project_key:
                    yield from self._yield_project_hierarchy_node(
                        project_key, project_name, seen_hierarchy_node_ids
                    )

                    parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
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
                    jira_client=self.jira_client,
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                    parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                ):
                    if include_permissions:
                        document.external_access = self._get_project_permissions(
                            project_key,
                            add_prefix=True,
                        )
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=f"Failed to process JSM issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        new_checkpoint.seen_hierarchy_node_ids = list(seen_hierarchy_node_ids)

        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JSM_FULL_PAGE_SIZE
        )

        return new_checkpoint

    def update_checkpoint_for_next_run(
        self,
        checkpoint: JsmConnectorCheckpoint,
        current_offset: int,
        starting_offset: int,
        page_size: int,
    ) -> None:
        if _is_cloud_client(self.jira_client):
            checkpoint.has_more = (
                len(checkpoint.all_issue_ids) > 0 or not checkpoint.ids_done
            )
        else:
            checkpoint.offset = current_offset
            checkpoint.has_more = current_offset - starting_offset == page_size

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        end = end or datetime.now().timestamp() + one_day

        jql = self._get_jql_query(start, end)
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []

        seen_hierarchy_node_ids: set[str] = set()

        while checkpoint.has_more:
            for issue in _perform_jql_search(
                jira_client=self.jira_client,
                jql=jql,
                start=current_offset,
                max_results=JIRA_SLIM_PAGE_SIZE,
                all_issue_ids=checkpoint.all_issue_ids,
                checkpoint_callback=checkpoint_callback,
                nextPageToken=checkpoint.cursor,
                ids_done=checkpoint.ids_done,
            ):
                project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
                project_key = project.key if project else None
                project_name = project.name if project else None

                if not project_key:
                    continue

                for node in self._yield_project_hierarchy_node(
                    project_key, project_name, seen_hierarchy_node_ids
                ):
                    slim_doc_batch.append(node)

                parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
                if parent:
                    for node in self._yield_parent_hierarchy_node_if_epic(
                        parent, project_key, seen_hierarchy_node_ids
                    ):
                        slim_doc_batch.append(node)

                if self._is_epic(issue):
                    for node in self._yield_epic_hierarchy_node(
                        issue, project_key, seen_hierarchy_node_ids
                    ):
                        slim_doc_batch.append(node)

                issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
                doc_id = build_jira_url(self.jira_base, issue_key)

                slim_doc_batch.append(
                    SlimDocument(
                        id=doc_id,
                        external_access=self._get_project_permissions(
                            project_key, add_prefix=False
                        ),
                        parent_hierarchy_raw_node_id=(
                            self._get_parent_hierarchy_raw_node_id(issue, project_key)
                            if project_key
                            else None
                        ),
                    )
                )
                current_offset += 1
                if len(slim_doc_batch) >= JIRA_SLIM_PAGE_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
            self.update_checkpoint_for_next_run(
                checkpoint, current_offset, prev_offset, JIRA_SLIM_PAGE_SIZE
            )
            prev_offset = current_offset

        if slim_doc_batch:
            yield slim_doc_batch

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        if self.jql_query:
            try:
                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=self.jql_query,
                            start=0,
                            max_results=1,
                            all_issue_ids=[],
                        )
                    ),
                    None,
                )
            except Exception as e:
                self._handle_jsm_connector_settings_error(e)

        elif self.jira_project:
            try:
                self.jira_client.project(self.jira_project)
            except Exception as e:
                self._handle_jsm_connector_settings_error(e)
        else:
            try:
                self.jira_client.projects()
            except Exception as e:
                self._handle_jsm_connector_settings_error(e)

    def _handle_jsm_connector_settings_error(self, e: Exception) -> None:
        status_code = getattr(e, "status_code", None)
        logger.error(f"JSM API error during validation: {e}")

        if status_code == 401:
            raise CredentialExpiredError(
                "Jira credential appears to be expired or invalid (HTTP 401)."
            )
        elif status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira token does not have sufficient permissions for this configuration (HTTP 403)."
            )
        elif status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira rate-limits being exceeded. Please try again later."
            )

        error_message = getattr(e, "text", None)
        if error_message is None:
            raise UnexpectedValidationError(
                f"Unexpected JSM error during validation: {e}"
            )

        raise ConnectorValidationError(
            f"Validation failed due to JSM error: {error_message}"
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint(
            has_more=True,
        )


def make_checkpoint_callback(
    checkpoint: JsmConnectorCheckpoint,
) -> Callable[[Iterator[list[str]], str | None], None]:
    def checkpoint_callback(
        issue_ids: Iterator[list[str]], pageToken: str | None
    ) -> None:
        for id_batch in issue_ids:
            checkpoint.all_issue_ids.append(id_batch)
        checkpoint.cursor = pageToken
        checkpoint.ids_done = pageToken is None

    return checkpoint_callback


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

    for slim_doc in connector.retrieve_all_slim_docs_perm_sync(
        start=start,
        end=end,
    ):
        print(slim_doc)

    for doc in load_all_from_connector(
        connector=connector,
        start=start,
        end=end,
    ).documents:
        print(doc)
