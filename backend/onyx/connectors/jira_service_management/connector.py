import copy
from datetime import datetime, timedelta
from typing import Any

from jira import JIRA
from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    JIRA_SLIM_PAGE_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
    time_str_to_utc,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira.connector import (
    JiraConnectorCheckpoint,
    is_cloud_client,
    make_checkpoint_callback,
    perform_jql_search,
    process_jira_issue,
)
from onyx.connectors.jira.utils import (
    best_effort_get_field_from_issue,
    build_jira_client,
    build_jira_url,
)
from onyx.connectors.jira_service_management.utils import (
    build_customer_portal_url,
    find_service_desk,
    get_current_status_name,
    get_customer_request,
    get_request_type_name,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600
_JSM_PAGE_SIZE = 50

_FIELD_CREATED = "created"
_FIELD_KEY = "key"
_FIELD_REQUEST_TYPE = "request_type"
_FIELD_REQUEST_STATUS = "request_status"
_FIELD_SERVICE_DESK_ID = "service_desk_id"
_FIELD_CUSTOMER_PORTAL_URL = "customer_portal_url"
_FIELD_CHANNEL = "channel"
_FIELD_LABELS = "labels"


class JiraServiceManagementConnectorCheckpoint(JiraConnectorCheckpoint):
    """Same layout as the Jira checkpoint.

    Kept as a distinct class so stored checkpoint JSON for the two sources can
    evolve independently.
    """


def build_jsm_document_id(jira_base_url: str, issue_key: str) -> str:
    """Document id for a JSM request.

    The Jira connector already uses the browse URL as the document id, so JSM
    docs get a fragment suffix to avoid overwriting a doc indexed through the
    plain Jira connector. The URL still opens the ticket.
    """
    return f"{build_jira_url(jira_base_url, issue_key)}#jira-service-management"


def process_service_desk_request(
    jira_client: JIRA,
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> Document | None:
    """Build a Document for a JSM customer request.

    The request is a Jira issue, so the base content comes from the Jira
    connector; the service-desk API then adds customer-facing fields
    (request type, customer-visible status, portal link).
    """
    document = process_jira_issue(
        jira_base_url=jira_base_url,
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
        labels_to_skip=labels_to_skip,
    )
    if document is None:
        return None

    document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    document.id = build_jsm_document_id(jira_base_url, issue.key)

    try:
        request = get_customer_request(jira_client, issue.key)
    except (CredentialExpiredError, InsufficientPermissionsError):
        raise
    except Exception as e:
        # Requests that are not customer-visible (or a servicedeskapi outage)
        # should not drop the ticket from the index.
        logger.warning(
            "Could not fetch JSM request view for %s; indexing without "
            "service desk metadata: %s",
            issue.key,
            e,
        )
        return document

    if request is None:
        return document

    if request_type := get_request_type_name(request):
        document.metadata[_FIELD_REQUEST_TYPE] = request_type
    if request_status := get_current_status_name(request):
        document.metadata[_FIELD_REQUEST_STATUS] = request_status
    if channel := request.get("channel"):
        if isinstance(channel, str):
            document.metadata[_FIELD_CHANNEL] = channel

    service_desk_id = request.get("serviceDeskId")
    if service_desk_id is not None:
        document.metadata[_FIELD_SERVICE_DESK_ID] = str(service_desk_id)
        if portal_url := build_customer_portal_url(
            jira_base_url, service_desk_id, issue.key
        ):
            document.metadata[_FIELD_CUSTOMER_PORTAL_URL] = portal_url

    return document


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraServiceManagementConnectorCheckpoint],
    SlimConnector,
):
    """Connector for Jira Service Management service desks.

    JSM customer requests are Jira issues, so fetching reuses the Jira
    connector's JQL machinery; `rest/servicedeskapi` adds the
    service-desk-specific fields. Only requests that are visible to the
    configured credentials are indexed.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: int | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # Custom JQL query to filter the indexed requests
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        self.batch_size = batch_size

        # dealing with scoped tokens is a bit tricky because we need to hit
        # api.atlassian.net when making requests but still want correct links
        # to issues in the UI. So, the user's base url is stored here, but
        # converted to a scoped url when passed to the jira client.
        self.jira_base = jira_base_url.rstrip("/")
        self.jira_project = project_key
        self.service_desk_id = service_desk_id
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jql_query = jql_query
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None

    @property
    def comment_email_blacklist(self) -> tuple[str, ...]:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    @property
    def quoted_jira_project(self) -> str:
        # Quote the project key to handle reserved words
        if not self.jira_project:
            return ""
        return f'"{self.jira_project}"'

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )

        # When only a service desk id is given, index that desk's backing
        # project so results stay scoped to the service desk.
        if self.service_desk_id is not None and not self.jira_project:
            service_desk = find_service_desk(
                self._jira_client, service_desk_id=self.service_desk_id
            )
            project_key = service_desk.get("projectKey") if service_desk else None
            if not isinstance(project_key, str) or not project_key:
                # fail closed: an unresolved desk id must not turn into an
                # unscoped sync of every visible Jira project
                raise ConnectorValidationError(
                    f"Could not resolve service desk '{self.service_desk_id}' "
                    "to its backing Jira project. Check that the service desk "
                    "exists and that the credential can view it."
                )
            self.jira_project = project_key

        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """JQL for the configured project/query plus the poll window.

        Unquoted epoch-ms so Jira does not reinterpret naive datetimes in the
        API user's profile timezone.
        https://support.atlassian.com/jira-software-cloud/docs/jql-fields/#Updated
        """
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"

        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        if self.jira_project:
            return f"project = {self.quoted_jira_project} AND {time_jql}"

        return time_jql

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)
        try:
            return (yield from self._load_from_checkpoint(jql, checkpoint))
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return (yield from self._load_from_checkpoint(jql, checkpoint))
            raise e

    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementConnectorCheckpoint]:
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)
        checkpoint_callback = make_checkpoint_callback(new_checkpoint)

        for issue in perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JSM_PAGE_SIZE,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                if document := process_service_desk_request(
                    jira_client=self.jira_client,
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    yield document
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=(
                        f"Failed to process Jira Service Management request: {e}"
                    ),
                    exception=e,
                )

            current_offset += 1

        self._update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JSM_PAGE_SIZE
        )
        return new_checkpoint

    def _update_checkpoint_for_next_run(
        self,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
        current_offset: int,
        starting_offset: int,
        page_size: int,
    ) -> None:
        if is_cloud_client(self.jira_client):
            # other updates are done in the checkpoint callback
            checkpoint.has_more = (
                len(checkpoint.all_issue_ids) > 0 or not checkpoint.ids_done
            )
        else:
            checkpoint.offset = current_offset
            # if we didn't retrieve a full batch, we're done
            checkpoint.has_more = current_offset - starting_offset == page_size

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        # add one day to account for any potential timezone issues
        end = end or datetime.now().timestamp() + one_day

        jql = self._get_jql_query(start, end)
        checkpoint = self.build_dummy_checkpoint()
        checkpoint_callback = make_checkpoint_callback(checkpoint)
        prev_offset = 0
        current_offset = 0
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []

        while checkpoint.has_more:
            for issue in perform_jql_search(
                jira_client=self.jira_client,
                jql=jql,
                start=current_offset,
                max_results=JIRA_SLIM_PAGE_SIZE,
                fields="created,key,labels",
                all_issue_ids=checkpoint.all_issue_ids,
                checkpoint_callback=checkpoint_callback,
                nextPageToken=checkpoint.cursor,
                ids_done=checkpoint.ids_done,
            ):
                issue_key = best_effort_get_field_from_issue(issue, _FIELD_KEY)

                labels = best_effort_get_field_from_issue(issue, _FIELD_LABELS)
                if labels and any(label in labels for label in self.labels_to_skip):
                    continue

                created = best_effort_get_field_from_issue(issue, _FIELD_CREATED)

                slim_doc_batch.append(
                    SlimDocument(
                        id=build_jsm_document_id(self.jira_base, issue_key),
                        doc_created_at=(time_str_to_utc(created) if created else None),
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

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        if self.jql_query:
            # Try to execute the JQL query with a small limit to validate its syntax
            try:
                next(
                    iter(
                        perform_jql_search(
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
                self._handle_settings_error(e)
            return

        if not self.jira_project and self.service_desk_id is None:
            # Index all requests the credential can see; just validate access.
            try:
                self.jira_client.projects()
            except Exception as e:
                self._handle_settings_error(e)
            return

        service_desk: dict[str, Any] | None = None
        try:
            service_desk = find_service_desk(
                self.jira_client,
                service_desk_id=self.service_desk_id,
                project_key=self.jira_project,
            )
        except Exception as e:
            self._handle_settings_error(e)

        if service_desk is None:
            if self.jira_project:
                raise ConnectorValidationError(
                    f"No Jira Service Management service desk found for project "
                    f"'{self.jira_project}'. Check that the project is a service "
                    "desk project and that the credential can view it."
                )
            raise ConnectorValidationError(
                f"No Jira Service Management service desk found with id "
                f"'{self.service_desk_id}'. Check that the service desk exists "
                "and that the credential can view it."
            )

    def _handle_settings_error(self, e: Exception) -> None:
        if isinstance(e, (CredentialExpiredError, InsufficientPermissionsError)):
            raise e

        status_code = getattr(e, "status_code", None)  # ods: ignore[getattr]
        logger.error("Jira Service Management API error during validation: %s", e)

        if status_code == 401:
            raise CredentialExpiredError(
                "Jira credential appears to be expired or invalid (HTTP 401)."
            )
        if status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira token does not have sufficient permissions for this "
                "configuration (HTTP 403)."
            )
        if status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira rate-limits being exceeded. "
                "Please try again later."
            )

        error_message = getattr(e, "text", None)  # ods: ignore[getattr]
        if error_message is None:
            raise UnexpectedValidationError(
                f"Unexpected Jira Service Management error during validation: {e}"
            )
        raise ConnectorValidationError(
            f"Validation failed due to Jira Service Management error: {error_message}"
        )

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint.model_validate_json(
            checkpoint_json
        )

    @override
    def build_dummy_checkpoint(self) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint(
            has_more=True,
        )
