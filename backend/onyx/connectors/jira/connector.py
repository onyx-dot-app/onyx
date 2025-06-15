import os
from collections.abc import Iterable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira import JIRA
from jira.resources import Issue
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
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira.utils import get_jira_project_key_from_issue
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

JIRA_API_VERSION = os.environ.get("JIRA_API_VERSION") or "2"
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


def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
) -> Iterable[Issue]:
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
    jira_client: JIRA,
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

    description = (
        issue.fields.description
        if JIRA_API_VERSION == "2"
        else extract_text_from_adf(issue.raw["fields"]["description"])
    )
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

    page_url = build_jira_url(jira_client, issue.key)

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
    offset: int | None = None


class JiraConnector(CheckpointedConnector[JiraConnectorCheckpoint], SlimConnector):
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
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")  # Remove trailing slash if present
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)

        self._jira_client: JIRA | None = None

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

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
        )
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Get the JQL query based on whether a specific project is set and time range"""
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

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
            return self._load_from_checkpoint(jql, checkpoint)
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return self._load_from_checkpoint(jql, checkpoint)
            raise e

    def _load_from_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        # Get the current offset from checkpoint or start at 0
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JIRA_FULL_PAGE_SIZE,
        ):
            issue_key = issue.key
            try:
                if document := process_jira_issue(
                    jira_client=self.jira_client,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_client, issue_key),
                    ),
                    failure_message=f"Failed to process Jira issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        # Update checkpoint
        checkpoint = JiraConnectorCheckpoint(
            offset=current_offset,
            # if we didn't retrieve a full batch, we're done
            has_more=current_offset - starting_offset == _JIRA_FULL_PAGE_SIZE,
        )
        return checkpoint

    def retrieve_all_slim_documents(
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

        slim_doc_batch = []
        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=int(start),
            max_results=_JIRA_SLIM_PAGE_SIZE,
        ):
            project_key = get_jira_project_key_from_issue(issue=issue)
            if not project_key:
                continue

            issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
            id = build_jira_url(self.jira_client, issue_key)
            slim_doc_batch.append(
                SlimDocument(
                    id=id,
                    external_access=get_project_permissions(
                        jira_client=self.jira_client, jira_project=project_key
                    ),
                )
            )
            if len(slim_doc_batch) >= _JIRA_SLIM_PAGE_SIZE:
                yield slim_doc_batch
                slim_doc_batch = []

        yield slim_doc_batch

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        # If a specific project is set, validate it exists
        if self.jira_project:
            try:
                self.jira_client.project(self.jira_project)
            except Exception as e:
                status_code = getattr(e, "status_code", None)

                if status_code == 401:
                    raise CredentialExpiredError(
                        "Jira credential appears to be expired or invalid (HTTP 401)."
                    )
                elif status_code == 403:
                    raise InsufficientPermissionsError(
                        "Your Jira token does not have sufficient permissions for this project (HTTP 403)."
                    )
                elif status_code == 404:
                    raise ConnectorValidationError(
                        f"Jira project not found with key: {self.jira_project}"
                    )
                elif status_code == 429:
                    raise ConnectorValidationError(
                        "Validation failed due to Jira rate-limits being exceeded. Please try again later."
                    )

                raise RuntimeError(f"Unexpected Jira error during validation: {e}")
        else:
            # If no project specified, validate we can access the Jira API
            try:
                # Try to list projects to validate access
                self.jira_client.projects()
            except Exception as e:
                status_code = getattr(e, "status_code", None)
                if status_code == 401:
                    raise CredentialExpiredError(
                        "Jira credential appears to be expired or invalid (HTTP 401)."
                    )
                elif status_code == 403:
                    raise InsufficientPermissionsError(
                        "Your Jira token does not have sufficient permissions to list projects (HTTP 403)."
                    )
                elif status_code == 429:
                    raise ConnectorValidationError(
                        "Validation failed due to Jira rate-limits being exceeded. Please try again later."
                    )

                raise RuntimeError(f"Unexpected Jira error during validation: {e}")

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(
            has_more=True,
        )


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

    for slim_doc in connector.retrieve_all_slim_documents(
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
