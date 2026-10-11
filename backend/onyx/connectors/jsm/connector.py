"""Jira Service Management connector.

Indexes the issues (customer requests) of Jira Service Management projects.
The JSM REST API (``/rest/servicedeskapi``) provides the service-desk scope;
issue search, fields, and comments come from the Jira platform API v3 the
same way the Jira connector reads them, and request types and participants
are attached per issue from the JSM API. Basic auth (Cloud email + API token)
and Data Center personal access tokens are supported, like the Jira connector.
"""

import copy
from datetime import datetime, timedelta
from typing import Any

from jira import JIRA
from jira.exceptions import JIRAError
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jsm.client import (
    build_jsm_session,
    fetch_service_desk,
    fetch_service_desks,
)
from onyx.connectors.jsm.connector_utils import (
    process_jsm_issue,
    process_jsm_issue_slim,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    DocumentFailure,
    SlimDocument,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600

_JSM_PAGE_SIZE = 50
_JSL_MAX_RESULTS = 5000


class JsmConnectorCheckpoint(ConnectorCheckpoint):
    offset: int | None = None


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JsmConnectorCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jsm_base_url: str,
        service_desk_id: str | None = None,
        jql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jsm_base = jsm_base_url.rstrip("/")
        self.service_desk_id = service_desk_id
        self.jql_query = jql_query
        self.batch_size = batch_size
        self._jira_client: JIRA | None = None
        self._jsm_session: Any = None
        self._desk_project_key_cache: str | None = None
        self._project_permissions_cache: dict[str, ExternalAccess | None] = {}

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jsm_base,
        )
        self._jsm_session = build_jsm_session(credentials)
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """The configured scope plus the poll window, with unquoted epoch-ms
        so Jira does not reinterpret naive datetimes in the API user's profile
        timezone (same convention as the Jira connector)."""
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"

        scopes: list[str] = []

        if self.jql_query:
            scopes.append(f"({self.jql_query})")

        if self.service_desk_id:
            # The JSM service desk id is not a JQL-searchable field, but each
            # desk is backed by a Jira project, so the desk scope is applied
            # as a project clause (project matches key, name, or id).
            project_key = self._service_desk_project_key()
            if project_key is None:
                logger.warning(
                    "Could not resolve service desk %s to a Jira project; "
                    "polling the unscoped time window.",
                    self.service_desk_id,
                )
            else:
                scopes.append(f'project = "{project_key}"')

        if not scopes:
            return time_jql

        return f"{' AND '.join(scopes)} AND {time_jql}"

    def _service_desk_project_key(self) -> str | None:
        """The Jira project id backing the configured service desk, resolved
        once per connector instance. Best effort: without the mapping the
        poll stays on the unscoped window rather than failing the sync."""
        if self._desk_project_key_cache is not None:
            return self._desk_project_key_cache
        if not (self._jsm_session and self.service_desk_id):
            return None
        try:
            desk = fetch_service_desk(
                self._jsm_session, self.jsm_base, self.service_desk_id
            )
        except Exception:
            logger.exception(
                "Failed to fetch service desk %s; polling without the desk scope.",
                self.service_desk_id,
            )
            return None
        project_id = desk.get("projectId") if desk else None
        if project_id:
            self._desk_project_key_cache = str(project_id)
        return self._desk_project_key_cache

    def _get_project_permissions(self, project_key: str, add_prefix: bool) -> Any:
        """External access for the Jira project backing a service desk.

        JSM permissions are the Jira project permissions; reuses the Jira
        connector's EE resolution (returns None outside EE, in which case the
        document keeps its default visibility). Cached per project/prefix.
        """
        cache_key = f"{project_key}:{'prefixed' if add_prefix else 'unprefixed'}"
        if cache_key not in self._project_permissions_cache:
            self._project_permissions_cache[cache_key] = get_project_permissions(
                jira_client=self.jira_client,
                jira_project=project_key,
                add_prefix=add_prefix,
            )
        return self._project_permissions_cache[cache_key]

    def _search_issues(
        self, jql: str, start: int, max_results: int
    ) -> list[dict[str, Any]]:
        try:
            issues = self.jira_client.search_issues(
                jql_str=jql,
                startAt=start,
                maxResults=max_results,
            )
        except JIRAError as e:
            self._handle_jsm_search_error(e)
            raise
        return [
            issue.raw if isinstance(issue.raw, dict) else dict(issue.raw)
            for issue in issues
        ]

    @staticmethod
    def _handle_jsm_search_error(e: JIRAError) -> None:
        if e.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credentials are expired or invalid (HTTP 401)."
            )
        if e.status_code == 403:
            raise InsufficientPermissionsError(
                "Insufficient permissions to search Jira Service Management issues."
            )
        if e.status_code == 400:
            raise ConnectorValidationError(
                f"Invalid JQL query or service desk. JQL error: {e.text}"
            )

    def _fetch_issues_page(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        page_size: int,
    ) -> list[dict[str, Any]]:
        jql = self._get_jql_query(start, end)
        return self._search_issues(jql, int(start), page_size)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        # JSM project permissions are the same Jira project permissions; the
        # EE layer reads them from the Jira client via the jira source, so the
        # perm-sync path reuses the non-perm documents here.
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        new_checkpoint = copy.deepcopy(checkpoint)
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset

        issues = self._search_issues(
            self._get_jql_query(start, end),
            starting_offset,
            _JSM_PAGE_SIZE,
        )

        project_key = self._service_desk_project_key() if include_permissions else None

        for issue in issues:
            issue_key = issue.get("key", "")
            try:
                if document := process_jsm_issue(
                    jsm_base=self.jsm_base,
                    issue=issue,
                    session=self._jsm_session,
                ):
                    if include_permissions and project_key is not None:
                        # Indexing path: prefix group ids with the source type
                        document.external_access = self._get_project_permissions(
                            project_key, add_prefix=True
                        )
                    yield document
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"{self.jsm_base}/browse/{issue_key}",
                        document_link=f"{self.jsm_base}/browse/{issue_key}",
                    ),
                    failure_message=f"Failed to process JSM issue: {str(e)}",
                    exception=e,
                )
            current_offset += 1

        new_checkpoint.offset = current_offset
        new_checkpoint.has_more = len(issues) == _JSM_PAGE_SIZE
        return new_checkpoint

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # ID-only path (e.g. pruning): pruning diffs document IDs and never
        # consumes permission data, so skip per-project permission resolution.
        yield from self._retrieve_all_slim_docs(
            start=start, end=end, include_permissions=False
        )

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(
            start=start, end=end, include_permissions=True
        )

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        *,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        # Mirror the Jira connector: default the window to [0, now + 1 day]
        # when the caller supplies no bounds.
        one_day = timedelta(hours=24).total_seconds()
        start = start if start is not None else 0
        end = end if end is not None else datetime.now().timestamp() + one_day

        project_key = self._service_desk_project_key() if include_permissions else None
        offset = 0
        slim_doc_batch: list[SlimDocument] = []

        while True:
            issues = self._search_issues(
                self._get_jql_query(start, end),
                offset,
                _JSM_PAGE_SIZE,
            )
            if not issues:
                break

            for issue in issues:
                if slim_doc := process_jsm_issue_slim(
                    self.jsm_base,
                    issue,
                    # Permission sync path: don't prefix; the upsert path
                    # handles prefixing.
                    external_access=(
                        self._get_project_permissions(project_key, add_prefix=False)
                        if include_permissions and project_key is not None
                        else None
                    ),
                ):
                    slim_doc_batch.append(slim_doc)
                if len(slim_doc_batch) >= _JSM_PAGE_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []

            offset += len(issues)
            if len(issues) < _JSM_PAGE_SIZE:
                break

        if slim_doc_batch:
            yield slim_doc_batch

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # A JSM install is a Jira install with the service desk API enabled;
        # list service desks to validate both the credential and the API.
        try:
            desks = fetch_service_desks(self._jsm_session, self.jsm_base)
        except Exception as e:
            self._handle_validation_error(e)
            return

        if self.service_desk_id:
            desk_ids = {str(desk.get("id")) for desk in desks}
            if self.service_desk_id not in desk_ids:
                raise ConnectorValidationError(
                    f"Service desk {self.service_desk_id} does not exist or "
                    f"is not accessible. Available desks: {sorted(desk_ids)}"
                )

        try:
            next(
                iter(
                    self._search_issues(
                        self._get_jql_query(
                            0,
                            datetime.now().timestamp()
                            + timedelta(days=1).total_seconds(),
                        ),
                        0,
                        1,
                    )
                ),
                None,
            )
        except Exception as e:
            self._handle_validation_error(e)

    @staticmethod
    def _handle_validation_error(e: Exception) -> None:
        logger.error("JSM API error during validation: %s", e)

        # client.jsm_get already maps 401/403 to the connector exception
        # hierarchy; let those carry their specific meaning.
        if isinstance(e, CredentialExpiredError):
            raise e
        if isinstance(e, InsufficientPermissionsError):
            raise e
        # A 400 mapped by client.jsm_get / _handle_jsm_search_error is a JQL
        # problem: keep the specific connector validation error instead of
        # downgrading it to the generic unexpected-validation error below.
        if isinstance(e, ConnectorValidationError):
            raise e
        # Jira answers invalid JQL on the search probe with HTTP 400.
        if (
            isinstance(e, JIRAError)
            and e.status_code == 400
            and not is_atlassian_date_error(e)
        ):
            raise ConnectorValidationError(
                f"Invalid JQL query or service desk. JQL error: {e.text}"
            )

        status_code = getattr(e, "status_code", None)  # ods: ignore[getattr]
        if status_code is None:
            response = getattr(e, "response", None)
            if response is not None:
                status_code = response.status_code

        if status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credential appears to be expired or invalid (HTTP 401)."
            )
        if status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira Service Management token does not have sufficient permissions (HTTP 403)."
            )
        if status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira Service Management rate-limits being exceeded. "
                "Please try again later."
            )
        raise UnexpectedValidationError(
            f"Unexpected Jira Service Management error during validation: {e}"
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint(
            has_more=True,
        )


if __name__ == "__main__":
    import os

    from tests.daily.connectors.utils import load_all_from_connector

    connector = JiraServiceManagementConnector(
        jsm_base_url=os.environ["JSM_BASE_URL"],
        service_desk_id=os.environ.get("JSM_SERVICE_DESK_ID"),
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
