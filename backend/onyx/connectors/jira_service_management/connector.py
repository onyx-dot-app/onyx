"""Jira Service Management Connector - pulls tickets from a specified JSM project."""

import copy
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira import JIRA
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
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
from onyx.connectors.jira.connector import (
    JiraConnectorCheckpoint,
    _perform_jql_search,
    process_jira_issue,
    _is_cloud_client,
    make_checkpoint_callback,
    _JIRA_FULL_PAGE_SIZE,
    ONE_HOUR,
)
from onyx.connectors.jira.utils import (
    build_jira_client,
    build_jira_url,
    get_jira_project_key_from_issue,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    """Connector for Jira Service Management projects.

    This connector pulls all tickets from a specified JSM project. JSM projects
    are specialized Jira projects for IT service management and customer support.
    """

    def __init__(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        """Initialize Jira Service Management connector.

        Args:
            jira_base_url: Base URL of the Jira instance (e.g., https://company.atlassian.net)
            jsm_project_key: The key of the JSM project to pull tickets from (required)
            comment_email_blacklist: List of email addresses to exclude from comments
            batch_size: Batch size for indexing
            labels_to_skip: List of labels that should cause tickets to be skipped
            scoped_token: Whether to use scoped token for API access
        """
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")
        self.jsm_project_key = jsm_project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
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
    def quoted_jsm_project(self) -> str:
        """Quote the project key to handle reserved words."""
        return f'"{self.jsm_project_key}"'

    def _get_project_permissions(self, project_key: str) -> Any:
        """Get project permissions with caching."""
        if project_key not in self._project_permissions_cache:
            self._project_permissions_cache[project_key] = get_project_permissions(
                jira_client=self.jira_client, jira_project=project_key
            )
        return self._project_permissions_cache[project_key]

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load credentials for Jira API access."""
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Build JQL query for JSM project with time range."""
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"
        project_jql = f"project = {self.quoted_jsm_project}"

        return f"{project_jql} AND {time_jql}"

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Load documents from checkpoint without permission sync."""
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
        """Load documents from checkpoint with permission information."""
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
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Internal method to load documents from checkpoint."""
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
                    # Update source to JIRA_SERVICE_MANAGEMENT
                    document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

                    # Add permission information if requested
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
                    failure_message=f"Failed to process JSM issue: {str(e)}",
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
        """Update checkpoint for next run."""
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
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Retrieve all slim documents with permission sync."""
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        end = end or datetime.now().timestamp() + one_day

        jql = self._get_jql_query(start, end)
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch = []

        from onyx.connectors.jira.utils import best_effort_get_field_from_issue

        _FIELD_KEY = "key"

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
                project_key = get_jira_project_key_from_issue(issue=issue)
                if not project_key:
                    continue

                issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
                if not issue_key:
                    continue

                id = build_jira_url(self.jira_base, issue_key)
                slim_doc_batch.append(
                    SlimDocument(
                        id=id,
                        external_access=self._get_project_permissions(project_key),
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
        """Validate connector settings and credentials."""
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # Validate that the JSM project exists and is accessible
        try:
            project = self.jira_client.project(self.jsm_project_key)
            logger.info(
                f"Validated JSM project: {project.key} - {project.name}"
            )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)

    def _handle_jira_connector_settings_error(self, e: Exception) -> None:
        """Handle Jira API errors during validation."""
        status_code = getattr(e, "status_code", None)
        logger.error(f"Jira API error during validation: {e}")

        if status_code == 401:
            raise CredentialExpiredError(
                "Jira credential appears to be expired or invalid (HTTP 401)."
            )
        elif status_code == 403:
            raise InsufficientPermissionsError(
                f"Your Jira token does not have sufficient permissions to access "
                f"project '{self.jsm_project_key}' (HTTP 403)."
            )
        elif status_code == 404:
            raise ConnectorValidationError(
                f"JSM project '{self.jsm_project_key}' not found or you don't have "
                f"access to it. Please verify the project key."
            )
        elif status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira rate-limits being exceeded. "
                "Please try again later."
            )

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
        """Validate checkpoint JSON."""
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        """Build a dummy checkpoint for initial sync."""
        return JiraConnectorCheckpoint(has_more=True)
