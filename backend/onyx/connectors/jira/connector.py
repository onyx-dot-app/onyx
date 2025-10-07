import copy
import os
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira import JIRA
from jira.resources import Issue
from more_itertools import chunked
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
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
from onyx.connectors.jira.utils import get_jira_project_key_from_issue
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()

ONE_HOUR = 3600

_MAX_RESULTS_FETCH_IDS = 5000  # 5000
_JIRA_SLIM_PAGE_SIZE = 500
_JIRA_FULL_PAGE_SIZE = 50

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
    """
    The caller should expect
    a) this function returns an iterable of issues of length 0 < len(issues) <= max_results.
       - caveat; if all_issue_ids is provided, the iterable will be the size of some sub-list.
       - this will only not match the above bound if a recent deployment changed max_results.

    IF the v3 API is used (i.e. the jira instance is a cloud instance), then the caller should expect:

    b) this function will call checkpoint_callback ONCE after at least one of the following has happened:
       - a new batch of ids has been fetched via enhanced search
       - a batch of issues has been bulk-fetched
    c) checkpoint_callback is called with the new all_issue_ids and the pageToken of the enhanced
       search request. We pass in a pageToken of None once we've fetched all the issue ids.

    Note: nextPageToken is valid for 7 days according to a post from a year ago, so for now
    we won't add any handling for restarting (just re-index, since there's no easy
    way to recover from this).
    """
    # it would be preferable to use one approach for both versions, but
    # v2 doesnt have the bulk fetch api and v3 has fully deprecated the search
    # api that v2 uses
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


def enhanced_search_ids(
    jira_client: JIRA, jql: str, nextPageToken: str | None = None
) -> tuple[list[str], str | None]:
    # https://community.atlassian.com/forums/Jira-articles/
    # Avoiding-Pitfalls-A-Guide-to-Smooth-Migration-to-Enhanced-JQL/ba-p/2985433
    # For cloud, it's recommended that we fetch all ids first then use the bulk fetch API.
    # The enhanced search isn't currently supported by our python library, so we have to
    # do this janky thing where we use the session directly.
    enhanced_search_path = jira_client._get_url("search/jql")
    params: dict[str, str | int | None] = {
        "jql": jql,
        "maxResults": _MAX_RESULTS_FETCH_IDS,
        "nextPageToken": nextPageToken,
        "fields": "id",
    }
    response = jira_client._session.get(enhanced_search_path, params=params).json()
    return [str(issue["id"]) for issue in response["issues"]], response.get(
        "nextPageToken"
    )


def bulk_fetch_issues(
    jira_client: JIRA, issue_ids: list[str], fields: str | None = None
) -> list[Issue]:
    # TODO: move away from this jira library if they continue to not support
    # the endpoints we need. Using private fields is not ideal, but
    # is likely fine for now since we pin the library version
    bulk_fetch_path = jira_client._get_url("issue/bulkfetch")

    # Prepare the payload according to Jira API v3 specification
    payload: dict[str, Any] = {"issueIdsOrKeys": issue_ids}

    # Only restrict fields if specified, might want to explicitly do this in the future
    # to avoid reading unnecessary data
    payload["fields"] = fields.split(",") if fields else ["*all"]

    try:
        response = jira_client._session.post(bulk_fetch_path, json=payload).json()
    except Exception as e:
        logger.error(f"Error fetching issues: {e}")
        raise e
    return [
        Issue(jira_client._options, jira_client._session, raw=issue)
        for issue in response["issues"]
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
    """
    The way this works is we get all the issue ids and bulk fetch them in batches.
    However, for really large deployments we can't do these operations sequentially,
    as it might take several hours to fetch all the issue ids.

    So, each run of this function does at least one of:
     - fetch a batch of issue ids
     - bulk fetch a batch of issues

    If all_issue_ids is not None, we use it to bulk fetch issues.
    """

    # with some careful synchronization these steps can be done in parallel,
    # leaving that out for now to avoid rate limit issues
    if not ids_done:
        new_ids, pageToken = enhanced_search_ids(jira_client, jql, nextPageToken)
        if checkpoint_callback is not None:
            checkpoint_callback(chunked(new_ids, max_results), pageToken)

    # bulk fetch issues from ids. Note that the above callback MAY mutate all_issue_ids,
    # but this fetch always just takes the last id batch.
    if all_issue_ids:
        yield from bulk_fetch_issues(jira_client, all_issue_ids.pop(), fields)


def _perform_jql_search_v2(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
) -> Iterable[Issue]:
    """
    Unfortunately, jira server/data center will forever use the v2 APIs that are now deprecated.
    """
    logger.debug(
        f"Fetching Jira issues with JQL: {jql}, "
        f"starting at {start}, max results: {max_results}"
    )
    issues = jira_client.search_issues(
        jql_str=jql,
        startAt=start,
        maxResults=max_results,
        fields=fields,
    )

    for issue in issues:
        if isinstance(issue, Issue):
            yield issue
        else:
            raise RuntimeError(f"Found Jira object not of type Issue: {issue}")


def process_jira_issue(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
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

    # Check ticket size
    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        logger.info(
            f"Skipping {issue.key} because it exceeds the maximum size of "
            f"{JIRA_CONNECTOR_MAX_TICKET_SIZE} bytes."
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
        source=DocumentSource.JIRA,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
    )


class JiraConnectorCheckpoint(ConnectorCheckpoint):
    # used for v3 (cloud) endpoint
    all_issue_ids: list[list[str]] = []
    ids_done: bool = False
    cursor: str | None = None
    # deprecated
    # Used for v2 endpoint (server/data center)
    offset: int | None = None


class JiraConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # Custom JQL query to filter Jira issues
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        self.batch_size = batch_size

        # dealing with scoped tokens is a bit tricky becasue we need to hit api.atlassian.net
        # when making jira requests but still want correct links to issues in the UI.
        # So, the user's base url is stored here, but converted to a scoped url when passed
        # to the jira client.
        self.jira_base = jira_base_url.rstrip("/")  # Remove trailing slash if present
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jql_query = jql_query
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
        # Cache project permissions to avoid fetching them repeatedly across runs
        self._project_permissions_cache: dict[str, Any] = {}

    @property
    def comment_email_blacklist(self) -> tuple:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")
        return self._jira_client

    @property
    def quoted_jira_project(self) -> str:
        # Quote the project name to handle reserved words
        if not self.jira_project:
            return ""
        return f'"{self.jira_project}"'

    def _get_project_permissions(self, project_key: str) -> Any:
        """Get project permissions with caching.

        Args:
            project_key: The Jira project key

        Returns:
            The external access permissions for the project
        """
        if project_key not in self._project_permissions_cache:
            self._project_permissions_cache[project_key] = get_project_permissions(
                jira_client=self.jira_client, jira_project=project_key
            )
        return self._project_permissions_cache[project_key]

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Get the JQL query based on configuration and time range

        If a custom JQL query is provided, it will be used and combined with time constraints.
        Otherwise, the query will be constructed based on project key (if provided).
        """
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

        # If custom JQL query is provided, use it and combine with time constraints
        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        # Otherwise, use project key if provided
        if self.jira_project:
            base_jql = f"project = {self.quoted_jira_project}"
            return f"{base_jql} AND {time_jql}"

        return time_jql

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
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
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Load documents from checkpoint with permission information included."""
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
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        # Get the current offset from checkpoint or start at 0
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)

        checkpoint_callback = make_checkpoint_callback(new_checkpoint)

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JIRA_FULL_PAGE_SIZE,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                if document := process_jira_issue(
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    # Add permission information to the document if requested
                    if include_permissions:
                        project_key = get_jira_project_key_from_issue(issue=issue)
                        if project_key:
                            document.external_access = self._get_project_permissions(
                                project_key
                            )
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=f"Failed to process Jira issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        # Update checkpoint
        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JIRA_FULL_PAGE_SIZE
        )

        return new_checkpoint

    def update_checkpoint_for_next_run(
        self,
        checkpoint: JiraConnectorCheckpoint,
        current_offset: int,
        starting_offset: int,
        page_size: int,
    ) -> None:
        if _is_cloud_client(self.jira_client):
            # other updates done in the checkpoint callback
            checkpoint.has_more = (
                len(checkpoint.all_issue_ids) > 0 or not checkpoint.ids_done
            )
        else:
            checkpoint.offset = current_offset
            # if we didn't retrieve a full batch, we're done
            checkpoint.has_more = current_offset - starting_offset == page_size

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        end = (
            end or datetime.now().timestamp() + one_day
        )  # we add one day to account for any potential timezone issues

        jql = self._get_jql_query(start, end)
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch = []

        while checkpoint.has_more:
            for issue in _perform_jql_search(
                jira_client=self.jira_client,
                jql=jql,
                start=current_offset,
                max_results=_JIRA_SLIM_PAGE_SIZE,
                all_issue_ids=checkpoint.all_issue_ids,
                checkpoint_callback=checkpoint_callback,
                nextPageToken=checkpoint.cursor,
                ids_done=checkpoint.ids_done,
            ):
                project_key = get_jira_project_key_from_issue(issue=issue)
                if not project_key:
                    continue

                issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
                id = build_jira_url(self.jira_base, issue_key)

                slim_doc_batch.append(
                    SlimDocument(
                        id=id,
                        external_access=self._get_project_permissions(project_key),
                    )
                )
                current_offset += 1
                if len(slim_doc_batch) >= _JIRA_SLIM_PAGE_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
            self.update_checkpoint_for_next_run(
                checkpoint, current_offset, prev_offset, _JIRA_SLIM_PAGE_SIZE
            )
            prev_offset = current_offset

        if slim_doc_batch:
            yield slim_doc_batch

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        # If a custom JQL query is set, validate it's valid
        if self.jql_query:
            try:
                # Try to execute the JQL query with a small limit to validate its syntax
                # Use next(iter(...), None) to get just the first result without
                # forcing evaluation of all results
                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=self.jql_query,
                            start=0,
                            max_results=1,
                        )
                    ),
                    None,
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)

        # If a specific project is set, validate it exists
        elif self.jira_project:
            try:
                self.jira_client.project(self.jira_project)
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
        else:
            # If neither JQL nor project specified, validate we can access the Jira API
            try:
                # Try to list projects to validate access
                self.jira_client.projects()
            except Exception as e:
                self._handle_jira_connector_settings_error(e)

    def _handle_jira_connector_settings_error(self, e: Exception) -> None:
        """Helper method to handle Jira API errors consistently.

        Extracts error messages from the Jira API response for all status codes when possible,
        providing more user-friendly error messages.

        Args:
            e: The exception raised by the Jira API

        Raises:
            CredentialExpiredError: If the status code is 401
            InsufficientPermissionsError: If the status code is 403
            ConnectorValidationError: For other HTTP errors with extracted error messages
        """
        status_code = getattr(e, "status_code", None)
        logger.error(f"Jira API error during validation: {e}")

        # Handle specific status codes with appropriate exceptions
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

        # Try to extract original error message from the response
        error_message = getattr(e, "text", None)
        if error_message is None:
            raise UnexpectedValidationError(
                f"Unexpected Jira error during validation: {e}"
            )

        raise ConnectorValidationError(
            f"Validation failed due to Jira error: {error_message}"
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(
            has_more=True,
        )


def make_checkpoint_callback(
    checkpoint: JiraConnectorCheckpoint,
) -> Callable[[Iterator[list[str]], str | None], None]:
    def checkpoint_callback(
        issue_ids: Iterator[list[str]], pageToken: str | None
    ) -> None:
        for id_batch in issue_ids:
            checkpoint.all_issue_ids.append(id_batch)
        checkpoint.cursor = pageToken
        # pageToken starts out as None and is only None once we've fetched all the issue ids
        checkpoint.ids_done = pageToken is None

    return checkpoint_callback


if __name__ == "__main__":
    import os
    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector

    # For connector permission testing, set EE to true.
    global_version.set_ee()

    connector = JiraConnector(
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

    for doc in load_all_docs_from_checkpoint_connector(
        connector=connector,
        start=start,
        end=end,
    ):
        print(doc)
