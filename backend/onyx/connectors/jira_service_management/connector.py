import copy
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira import JIRA
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.connector import (
    _FIELD_KEY,
    _FIELD_PROJECT,
    _is_cloud_client,
    _perform_jql_search,
    JiraConnectorCheckpoint,
    make_checkpoint_callback,
)
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    """
    Connector for Jira Service Management (JSM) projects.

    Jira Service Management is a specialized Jira variant for IT service management,
    customer support, and operations. This connector targets specific JSM projects
    and can optionally filter by JSM-specific issue types.

    Reuses the existing Jira connector infrastructure (utilities, permission sync,
    checkpointing, etc.) while providing JSM-specific project targeting.
    """

    def __init__(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jsm_issue_types: list[str] | None = None,
        scoped_token: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")
        self.jsm_project_key = jsm_project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jsm_issue_types = jsm_issue_types
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
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
    def quoted_jsm_project_key(self) -> str:
        return f'"{self.jsm_project_key}"'

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

    def _build_jsm_jql(self, start: float, end: float) -> str:
        """
        Build a JQL query targeting a specific JSM project.

        If jsm_issue_types is provided with non-blank entries, also filters by
        those issue types (e.g., Incident, Service Request, Problem, Change).
        If empty, blank-only, or not provided, all issue types in the JSM
        project are included.
        """
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        jql = f"project = {self.quoted_jsm_project_key}"

        # Only add issuetype filter when there are non-blank entries to avoid
        # producing `issuetype in ()` which Jira rejects.
        if self.jsm_issue_types:
            cleaned = [it.strip() for it in self.jsm_issue_types if it.strip()]
            if cleaned:
                issue_type_clause = ", ".join(f'"{t}"' for t in cleaned)
                jql += f" AND issuetype in ({issue_type_clause})"

        jql += f" AND updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

        return jql

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def _load_from_checkpoint(
        self,
        start: float,
        end: float,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        jql = self._build_jsm_jql(start, end)
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)

        checkpoint_callback = make_checkpoint_callback(new_checkpoint)

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=50,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                # Get JSM project key from the issue
                project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
                project_key_single = project.key if project else self.jsm_project_key

                if document := process_jira_issue(
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    # Override the source to JIRA_SERVICE_MANAGEMENT
                    document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

                    if include_permissions:
                        document.external_access = self._get_project_permissions(
                            project_key_single,
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

        self._update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, 50
        )

        return new_checkpoint

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        try:
            return self._load_from_checkpoint(
                start, end, checkpoint, include_permissions=False
            )
        except Exception as e:
            if is_atlassian_date_error(e):
                return self._load_from_checkpoint(
                    start - ONE_HOUR, end, checkpoint, include_permissions=False
                )
            raise e

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        try:
            return self._load_from_checkpoint(
                start, end, checkpoint, include_permissions=True
            )
        except Exception as e:
            if is_atlassian_date_error(e):
                return self._load_from_checkpoint(
                    start - ONE_HOUR, end, checkpoint, include_permissions=True
                )
            raise e

    def _update_checkpoint_for_next_run(
        self,
        checkpoint: JiraConnectorCheckpoint,
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
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        end = end or datetime.now().timestamp() + one_day

        jql = self._build_jsm_jql(start, end)
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []

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
                issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
                doc_id = build_jira_url(self.jira_base, issue_key)

                slim_doc_batch.append(
                    SlimDocument(
                        id=doc_id,
                        external_access=self._get_project_permissions(
                            self.jsm_project_key, add_prefix=False
                        ),
                    )
                )
                current_offset += 1
                if len(slim_doc_batch) >= JIRA_SLIM_PAGE_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
            self._update_checkpoint_for_next_run(
                checkpoint, current_offset, prev_offset, JIRA_SLIM_PAGE_SIZE
            )
            prev_offset = current_offset

        if slim_doc_batch:
            yield slim_doc_batch

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        try:
            self.jira_client.project(self.jsm_project_key)
        except Exception as e:
            self._handle_validation_error(e)

    def _handle_validation_error(self, e: Exception) -> None:
        status_code = getattr(e, "status_code", None)
        logger.error("Jira API error during validation: %s", e)

        if status_code == 401:
            raise CredentialExpiredError(
                "Jira credential appears to be expired or invalid (HTTP 401)."
            )
        elif status_code == 403:
            raise ConnectorValidationError(
                "Your Jira token does not have sufficient permissions for this JSM project (HTTP 403)."
            )
        elif status_code == 404:
            raise ConnectorValidationError(
                f"JSM project '{self.jsm_project_key}' not found. Please verify the project key is correct and you have access to it."
            )
        elif status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira rate-limits being exceeded. Please try again later."
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
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(
            has_more=True,
        )


if __name__ == "__main__":
    import os

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        jsm_project_key=os.environ["JSM_PROJECT_KEY"],
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
