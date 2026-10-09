"""Jira Service Management connector.

Indexes the issues (customer requests) of Jira Service Management projects.
The JSM REST API (``/rest/servicedeskapi``) provides the service-desk scope;
issue search, fields, and comments come from the Jira platform API v3 the
same way the Jira connector reads them, and request types and participants
are attached per issue from the JSM API. Basic auth (Cloud email + API token)
and Data Center personal access tokens are supported, like the Jira connector.
"""

import copy
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from jira import JIRA
from jira.exceptions import JIRAError
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
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
from onyx.connectors.jira.connector import (
    _perform_jql_search,
    make_checkpoint_callback,
)
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION, build_jira_client
from onyx.connectors.jsm.client import build_jsm_session, fetch_service_desks
from onyx.connectors.jsm.connector_utils import (
    is_oversized_jsm_issue,
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


class JsmConnectorCheckpoint(ConnectorCheckpoint):
    # used for v3 (cloud) endpoint
    all_issue_ids: list[list[str]] = []
    ids_done: bool = False
    cursor: str | None = None
    # used for v2 endpoint (server/data center)
    offset: int | None = None
    # keys whose bodies exceeded the size limit and were skipped by the full
    # path; lets slim retrieval exclude the same tickets
    oversized_issue_keys: list[str] = []


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
        # cache of the Jira project key backing the configured service desk
        # ("" while unresolvable so a failed lookup is not retried every poll)
        self._desk_project_key: str | None = None
        self._project_permissions_cache: dict[str, Any] = {}

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

        scope_jql = self._get_scope_jql()
        if scope_jql:
            return f"{scope_jql} AND {time_jql}"

        return time_jql

    def _get_scope_jql(self) -> str:
        """JQL for the configured service desk / custom query, without the
        poll window. A service desk is backed by exactly one Jira project, so
        the desk is translated to a project filter; otherwise every project
        the credential can access would be indexed."""
        if self.jql_query:
            if self.service_desk_id:
                project_key = self._get_project_key_for_service_desk()
                if project_key:
                    return f"((project = {project_key}) AND ({self.jql_query}))"
                return f"({self.jql_query})"
            return f"({self.jql_query})"

        if self.service_desk_id:
            project_key = self._get_project_key_for_service_desk()
            if project_key:
                return f"project = {project_key}"

        return ""

    def _get_project_key_for_service_desk(self) -> str | None:
        """The Jira project key backing the configured service desk, resolved
        once per instance. JSM issues do not carry their desk in a queryable
        field, but a desk maps 1:1 to a project, so scoping by project keeps
        the poll inside the selected desk."""
        if self._desk_project_key is not None:
            return self._desk_project_key

        if self._jsm_session is None or not self.service_desk_id:
            return None

        self._desk_project_key = ""
        try:
            desks = fetch_service_desks(self._jsm_session, self.jsm_base)
        except Exception:
            logger.exception(
                "Failed to resolve service desk %s to its project; "
                "polling without the desk filter.",
                self.service_desk_id,
            )
            return None

        for desk in desks:
            if str(desk.get("id")) == self.service_desk_id:
                # the JSM service desk payload links the desk to its project
                # via projectId; resolve the project key from the Jira client
                project_id = desk.get("projectId")
                if not project_id:
                    return None
                try:
                    project = self.jira_client.project(project_id)
                    project_key = getattr(project, "key", None)
                except Exception:
                    logger.exception(
                        "Failed to fetch Jira project %s for service desk %s.",
                        project_id,
                        self.service_desk_id,
                    )
                    return None
                if project_key:
                    self._desk_project_key = project_key
                    return project_key
                return None

        logger.warning(
            "Service desk %s is no longer visible to the credential; "
            "polling without the desk filter.",
            self.service_desk_id,
        )
        return None

    def _is_cloud_client(self) -> bool:
        return (
            self._jira_client is not None
            and self._jira_client._options["rest_api_version"] == JIRA_CLOUD_API_VERSION
        )

    def _search_issues_iter(
        self,
        jql: str,
        start: int,
        max_results: int,
        checkpoint: JsmConnectorCheckpoint,
    ) -> Iterable[Any]:
        """Issue resources for one page of the JQL search.

        Cloud clients use the enhanced JQL search + bulk fetch path (the legacy
        ``/search`` route is deprecated there and bypassed by JiraConnector),
        with the id batches / page token tracked on the checkpoint so paging
        progresses across checkpoint runs. Data Center keeps the offset-based
        v2 search."""
        try:
            if self._is_cloud_client():
                return _perform_jql_search(
                    jira_client=self.jira_client,
                    jql=jql,
                    start=start,
                    max_results=max_results,
                    all_issue_ids=checkpoint.all_issue_ids,
                    checkpoint_callback=make_checkpoint_callback(checkpoint),
                    nextPageToken=checkpoint.cursor,
                    ids_done=checkpoint.ids_done,
                )
            return iter(
                self.jira_client.search_issues(
                    jql_str=jql,
                    startAt=start,
                    maxResults=max_results,
                )
            )
        except JIRAError as e:
            self._handle_jsm_search_error(e)
            raise

    @staticmethod
    def _issue_to_raw_dict(issue: Any) -> dict[str, Any]:
        return issue.raw if isinstance(issue.raw, dict) else dict(issue.raw)

    def _get_project_permissions(self, project_key: str) -> Any:
        """The project's external access with caching (None when EE is off or
        the project has no restrictions), mirroring the Jira connector."""
        if not project_key:
            return None
        if project_key not in self._project_permissions_cache:
            self._project_permissions_cache[project_key] = get_project_permissions(
                jira_client=self.jira_client,
                jira_project=project_key,
                add_prefix=True,  # indexing path - prefix here
            )
        return self._project_permissions_cache[project_key]

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

        raw_issues = [
            self._issue_to_raw_dict(issue)
            for issue in self._search_issues_iter(
                self._get_jql_query(start, end),
                starting_offset,
                _JSM_PAGE_SIZE,
                new_checkpoint,
            )
        ]

        for issue in raw_issues:
            issue_key = issue.get("key", "")
            try:
                if document := process_jsm_issue(
                    jsm_base=self.jsm_base,
                    issue=issue,
                    session=self._jsm_session,
                ):
                    if include_permissions:
                        project_key = self._get_issue_project_key(issue)
                        document.external_access = self._get_project_permissions(
                            project_key
                        )
                    yield document
                elif is_oversized_jsm_issue(issue):
                    # the full path drops oversized tickets; record that in the
                    # checkpoint so slim retrieval does not treat them as done
                    new_checkpoint.oversized_issue_keys.append(issue_key)
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
        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JSM_PAGE_SIZE
        )
        return new_checkpoint

    def update_checkpoint_for_next_run(
        self,
        checkpoint: JsmConnectorCheckpoint,
        current_offset: int,
        starting_offset: int,
        page_size: int,
    ) -> None:
        """The same split the Jira connector uses: cloud paging is driven by
        the id batches / page token in the checkpoint, data center by offset."""
        if self._is_cloud_client():
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
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(
            start=start,
            end=end,
            include_permissions=False,
        )

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(
            start=start,
            end=end,
            include_permissions=True,
        )

    def _get_issue_project_key(self, issue: dict[str, Any]) -> str:
        fields = issue.get("fields") or {}
        project = fields.get("project") or {}
        return project.get("key", "") or ""

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        include_permissions: bool = False,
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()

        start = start or 0
        end = (
            end or datetime.now().timestamp() + one_day
        )  # we add one day to account for any potential timezone issues

        jql = self._get_jql_query(start, end)
        checkpoint = self.build_dummy_checkpoint()
        offset = 0
        slim_doc_batch: list[SlimDocument] = []

        while True:
            issues = [
                self._issue_to_raw_dict(issue)
                for issue in self._search_issues_iter(
                    jql,
                    offset,
                    _JSM_PAGE_SIZE,
                    checkpoint,
                )
            ]
            if not issues:
                break

            for issue in issues:
                if is_oversized_jsm_issue(issue):
                    # keep slim retrieval in step with the full path, which
                    # drops oversized tickets instead of indexing them
                    continue

                slim_document = process_jsm_issue_slim(self.jsm_base, issue)
                # Permission sync path - don't prefix, the perm-sync upsert
                # handles prefixing (same split as Jira)
                if include_permissions:
                    slim_document.external_access = self._get_project_permissions(
                        self._get_issue_project_key(issue)
                    )
                slim_doc_batch.append(slim_document)
                if len(slim_doc_batch) >= _JSM_PAGE_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []

            offset += len(issues)
            self.update_checkpoint_for_next_run(
                checkpoint, offset, offset - len(issues), _JSM_PAGE_SIZE
            )
            if not checkpoint.has_more:
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
                    self._search_issues_iter(
                        self._get_jql_query(
                            0,
                            datetime.now().timestamp()
                            + timedelta(days=1).total_seconds(),
                        ),
                        0,
                        1,
                        self.build_dummy_checkpoint(),
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
