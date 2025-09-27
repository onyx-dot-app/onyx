import copy
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
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.connector import _is_cloud_client
from onyx.connectors.jira.connector import _JIRA_FULL_PAGE_SIZE
from onyx.connectors.jira.connector import _JIRA_SLIM_PAGE_SIZE
from onyx.connectors.jira.connector import _perform_jql_search
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.connector import make_checkpoint_callback
from onyx.connectors.jira.connector import ONE_HOUR
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira.utils import get_jira_project_key_from_issue
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()

# Constants for Jira Service Management field names
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


def process_jira_service_management_issue(
    jira_client: JIRA,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> Document | None:
    """Process a Jira Service Management issue into a Document.

    Args:
        jira_client: The Jira client instance
        issue: The Jira Service Management issue to process
        comment_email_blacklist: Tuple of email addresses to exclude from comments

    Returns:
        A Document object containing the processed issue data, or None if processing fails
    """
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

    page_url = build_jira_url(jira_client, issue.key)

    metadata_dict: dict[str, str | list[str]] = {}
    people = set()

    # Extract reporter information
    creator = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
    if creator is not None and (
        basic_expert_info := best_effort_basic_expert_info(creator)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_REPORTER] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_REPORTER_EMAIL] = email

    # Extract assignee information
    assignee = best_effort_get_field_from_issue(issue, _FIELD_ASSIGNEE)
    if assignee is not None and (
        basic_expert_info := best_effort_basic_expert_info(assignee)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_ASSIGNEE] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_ASSIGNEE_EMAIL] = email

    # Extract other metadata
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
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
    )


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraConnectorCheckpoint], LoadConnector, SlimConnector
):
    def __init__(
        self,
        jira_service_management_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # Custom JQL query to filter Jira Service Management issues
        jql_query: str | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_service_management_base_url.rstrip("/")
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jql_query = jql_query

        self._jira_client: JIRA | None = None

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
        # Quote the project name to handle reserved words
        if not self.jira_project:
            return ""
        return f'"{self.jira_project}"'

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Convert JSM credentials to standard Jira format for client
        jira_credentials = {
            "jira_user_email": credentials["jira_service_management_email"],
            "jira_api_token": credentials["jira_service_management_api_token"],
        }

        self._jira_client = build_jira_client(
            credentials=jira_credentials,
            jira_base=self.jira_base,
        )
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Get the JQL query for Service Management issues based on configuration and time range.

        If a custom JQL query is provided, it will be used and combined with time constraints.
        Otherwise, the query will be constructed based on project key (if provided) or
        will default to filtering service desk projects.

        Args:
            start: Start timestamp (seconds since Unix epoch) for the query time range
            end: End timestamp (seconds since Unix epoch) for the query time range

        Returns:
            JQL query string that filters for service management issues within the specified
            time range.
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

        # Use project key if provided - focus on that specific project
        if self.jira_project:
            base_jql = f"project = {self.quoted_jira_project}"
            return f"{base_jql} AND {time_jql}"

        # If no specific project, filter to only service desk projects
        # This ensures we only pull JSM tickets, not regular Jira tickets
        service_desk_jql = "project in projectsWhereUserHasPermission('Browse Projects') AND projectType = 'service_desk'"
        return f"{service_desk_jql} AND {time_jql}"

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
                if document := process_jira_service_management_issue(
                    jira_client=self.jira_client,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    yield document

            except Exception as e:
                # Log the full exception for debugging but use a generic message for the failure
                logger.error(
                    f"Failed to process Jira Service Management issue {issue_key}: "
                    f"Error type: {type(e).__name__}, Status code: {getattr(e, 'status_code', 'N/A')}"
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_client, issue_key),
                    ),
                    failure_message="Failed to process Jira Service Management issue due to an unexpected error",
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
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch = []
        while checkpoint.has_more:
            if callback and callback.should_stop():
                raise RuntimeError("retrieve_all_slim_documents: Stop signal detected")

            for issue in _perform_jql_search(
                jira_client=self.jira_client,
                jql=jql,
                start=current_offset,
                # Use Jira-optimized page size for slim operations rather than self.batch_size
                # Slim docs only need basic metadata, so larger batches (500) are efficient
                # Full document processing uses smaller batches (50) due to content processing overhead
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
                id = build_jira_url(self.jira_client, issue_key)
                slim_doc_batch.append(
                    SlimDocument(
                        id=id,
                        external_access=get_project_permissions(
                            jira_client=self.jira_client, jira_project=project_key
                        ),
                    )
                )
                current_offset += 1
                if len(slim_doc_batch) >= _JIRA_SLIM_PAGE_SIZE:
                    if callback:
                        callback.progress(
                            "retrieve_all_slim_documents", len(slim_doc_batch)
                        )
                    yield slim_doc_batch
                    slim_doc_batch = []
            self.update_checkpoint_for_next_run(
                checkpoint, current_offset, prev_offset, _JIRA_SLIM_PAGE_SIZE
            )
            prev_offset = current_offset

        if slim_doc_batch:
            yield slim_doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from JSM without time constraints (for full reindex)"""
        # Use a very wide time range to get all documents
        start_time = 0  # Unix epoch
        end_time = int(datetime.now().timestamp())

        checkpoint = self.build_dummy_checkpoint()

        for doc_or_failure in self.load_from_checkpoint(
            start_time, end_time, checkpoint
        ):
            if isinstance(doc_or_failure, Document):
                yield [doc_or_failure]
            # Skip failures in load_from_state to avoid interrupting full reindex

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # If a custom JQL query is set, validate it's valid
        if self.jql_query:
            try:
                # Try to execute the JQL query with a small limit to validate its syntax
                # Use next(iter(...), None) to get just the first result without
                # forcing evaluation of all results
                if _is_cloud_client(self.jira_client):
                    # For Jira Cloud, we need to provide all_issue_ids parameter
                    dummy_checkpoint = self.build_dummy_checkpoint()
                    next(
                        iter(
                            _perform_jql_search(
                                jira_client=self.jira_client,
                                jql=self.jql_query,
                                start=0,
                                max_results=1,
                                all_issue_ids=dummy_checkpoint.all_issue_ids,
                                nextPageToken=dummy_checkpoint.cursor,
                                ids_done=dummy_checkpoint.ids_done,
                            )
                        ),
                        None,
                    )
                else:
                    # For Jira Server
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
        error_type = type(e).__name__
        logger.error(
            f"Jira Service Management API error during validation. Status code: {status_code}, Error type: {error_type}"
        )

        # Handle specific status codes with appropriate exceptions
        if status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credential appears to be expired or invalid (HTTP 401)."
            )
        elif status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira Service Management token does not have sufficient permissions for this configuration (HTTP 403)."
            )
        elif status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira Service Management rate-limits being exceeded. Please try again later."
            )

        # Try to extract original error message from the response
        error_message = getattr(e, "text", None)
        if error_message is None:
            raise UnexpectedValidationError(
                f"Unexpected Jira Service Management error during validation: {e}"
            )

        raise ConnectorValidationError(
            f"Validation failed due to Jira Service Management error: {error_message}"
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(
            has_more=True,
        )
