"""Connector for Jira Service Management.

JSM requests are stored as Jira issues in service desk projects.
This connector discovers service desks via the JSM REST API and indexes
their requests using the same Jira issue processing pipeline.
"""

import copy
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira import JIRA
from jira.resources import Issue
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
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.jira.connector import (
    _JIRA_FULL_PAGE_SIZE,
    _perform_jql_search,
    make_checkpoint_callback,
    process_jira_issue,
)
from onyx.connectors.jira.utils import (
    best_effort_get_field_from_issue,
    build_jira_client,
    build_jira_url,
    JIRA_CLOUD_API_VERSION,
)
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600

_FIELD_PROJECT = "project"
_FIELD_KEY = "key"


def _is_cloud_client(jira_client: JIRA) -> bool:
    return jira_client._options["rest_api_version"] == JIRA_CLOUD_API_VERSION


def _discover_service_desk_projects(
    jira_client: JIRA,
) -> list[dict[str, Any]]:
    """Discover service desk projects via the JSM REST API."""
    service_desks: list[dict[str, Any]] = []
    start = 0
    limit = 50

    while True:
        path = jira_client._get_url("rest/servicedeskapi/servicedesk")
        params: dict[str, Any] = {"start": start, "limit": limit}
        try:
            response = jira_client._session.get(path, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.warning(
                "Failed to fetch service desks via JSM API: %s. "
                "Falling back to all-project discovery.",
                e,
            )
            return []

        service_desks.extend(data.get("values", []))
        total = data.get("total", len(service_desks))
        start += limit
        if start >= total:
            break

    return service_desks


def _discover_all_projects(
    jira_client: JIRA,
) -> list[dict[str, Any]]:
    """Fallback: list all projects as service desk candidates."""
    try:
        return [
            {"projectKey": p.key, "projectName": p.name, "id": str(p.id)}
            for p in jira_client.projects()
        ]
    except Exception as e:
        logger.error("Failed to list Jira projects: %s", e)
        return []


def _build_service_desk_jql(
    project_keys: list[str],
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> str:
    start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M"
    )
    end_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M"
    )
    projects = ", ".join(f'"{p}"' for p in project_keys)
    return (
        f"project IN ({projects}) "
        f"AND updated >= '{start_str}' AND updated <= '{end_str}'"
    )


class JiraServiceManagementCheckpoint(ConnectorCheckpoint):
    all_issue_ids: list[list[str]] = []
    ids_done: bool = False
    cursor: str | None = None
    offset: int | None = None
    seen_hierarchy_node_ids: list[str] = []


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraServiceManagementCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        project_keys: list[str] | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")
        self.project_keys = project_keys
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
        self._resolved_project_keys: list[str] | None = None

    @property
    def comment_email_blacklist(self) -> tuple:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    # ---- Project discovery ----

    def _resolve_project_keys(self) -> list[str]:
        if self._resolved_project_keys is not None:
            return self._resolved_project_keys

        if self.project_keys:
            self._resolved_project_keys = self.project_keys
        else:
            desks = _discover_service_desk_projects(self.jira_client)
            if desks:
                self._resolved_project_keys = [sd["projectKey"] for sd in desks]
            else:
                projects = _discover_all_projects(self.jira_client)
                self._resolved_project_keys = [p["projectKey"] for p in projects]

        if not self._resolved_project_keys:
            logger.warning("No service desk projects found.")
        return self._resolved_project_keys

    def _get_jql(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        keys = self._resolve_project_keys()
        if not keys:
            return "issue = NULL"
        return _build_service_desk_jql(keys, start, end)

    # ---- Credentials ----

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    # ---- Helpers ----

    def _get_project_info(
        self, issue: Issue
    ) -> tuple[str | None, str | None]:
        project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
        if project is None:
            return None, None
        return project.key, project.name

    def _yield_project_hierarchy_node(
        self,
        project_key: str,
        project_name: str | None,
        seen_ids: set[str],
    ) -> Generator[HierarchyNode, None, None]:
        if project_key in seen_ids:
            return
        seen_ids.add(project_key)
        yield HierarchyNode(
            raw_node_id=project_key,
            display_name=project_name or project_key,
            link=f"{self.jira_base}/projects/{project_key}",
            node_type=HierarchyNodeType.PROJECT,
        )

    def _document_from_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        doc = process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        )
        if doc is not None:
            doc.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
        return doc

    def _update_has_more(
        self, checkpoint: JiraServiceManagementCheckpoint
    ) -> None:
        if _is_cloud_client(self.jira_client):
            checkpoint.has_more = (
                len(checkpoint.all_issue_ids) > 0 or not checkpoint.ids_done
            )
        else:
            # v2 uses offset-based pagination; has_more is set by
            # the caller comparing offset deltas against page size
            pass

    # ---- Checkpointed loading ----

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        jql = self._get_jql(start, end)
        try:
            yield from self._load_from_checkpoint(jql, checkpoint, False)
        except Exception as e:
            if is_atlassian_date_error(e):
                yield from self._load_from_checkpoint(
                    self._get_jql(start - ONE_HOUR, end), checkpoint, False
                )
            else:
                raise e

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        jql = self._get_jql(start, end)
        try:
            yield from self._load_from_checkpoint(jql, checkpoint, True)
        except Exception as e:
            if is_atlassian_date_error(e):
                yield from self._load_from_checkpoint(
                    self._get_jql(start - ONE_HOUR, end), checkpoint, True
                )
            else:
                raise e

    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraServiceManagementCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)
        seen_hierarchy_node_ids = set(new_checkpoint.seen_hierarchy_node_ids)

        ckpt_cb = make_checkpoint_callback(new_checkpoint)

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JIRA_FULL_PAGE_SIZE,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=ckpt_cb,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                project_key, project_name = self._get_project_info(issue)
                if project_key:
                    yield from self._yield_project_hierarchy_node(
                        project_key, project_name, seen_hierarchy_node_ids
                    )

                if doc := self._document_from_issue(
                    issue, parent_hierarchy_raw_node_id=project_key
                ):
                    yield doc

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
        self._update_has_more(new_checkpoint)
        if not _is_cloud_client(self.jira_client):
            new_checkpoint.offset = current_offset
            new_checkpoint.has_more = (
                current_offset - starting_offset == _JIRA_FULL_PAGE_SIZE
            )
        return new_checkpoint

    # ---- Slim docs ----

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        one_day = timedelta(hours=24).total_seconds()
        start = start or 0
        end = end or (datetime.now().timestamp() + one_day)

        jql = self._get_jql(start, end)
        cp = self.build_dummy_checkpoint()
        ckpt_cb = make_checkpoint_callback(cp)
        prev_offset = 0
        current_offset = 0
        batch: list[SlimDocument | HierarchyNode] = []
        seen_hids: set[str] = set()

        while cp.has_more:
            for issue in _perform_jql_search(
                jira_client=self.jira_client,
                jql=jql,
                start=current_offset,
                max_results=JIRA_SLIM_PAGE_SIZE,
                all_issue_ids=cp.all_issue_ids,
                checkpoint_callback=ckpt_cb,
                nextPageToken=cp.cursor,
                ids_done=cp.ids_done,
            ):
                project_key, _ = self._get_project_info(issue)
                if not project_key:
                    continue
                for node in self._yield_project_hierarchy_node(
                    project_key, None, seen_hids
                ):
                    batch.append(node)

                key = best_effort_get_field_from_issue(issue, _FIELD_KEY)
                batch.append(
                    SlimDocument(
                        id=build_jira_url(self.jira_base, key),
                        parent_hierarchy_raw_node_id=project_key,
                    )
                )
                current_offset += 1
                if len(batch) >= JIRA_SLIM_PAGE_SIZE:
                    yield batch
                    batch = []

            self._update_has_more(cp)
            if not _is_cloud_client(self.jira_client):
                cp.offset = current_offset
                cp.has_more = current_offset - prev_offset == JIRA_SLIM_PAGE_SIZE
                prev_offset = current_offset

        if batch:
            yield batch

    # ---- Validation ----

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            self.jira_client.projects()
        except Exception as e:
            self._handle_validation_error(e)

    def _handle_validation_error(self, e: Exception) -> None:
        status_code = getattr(e, "status_code", None)
        logger.error("JSM API error during validation: %s", e)
        if status_code == 401:
            raise CredentialExpiredError(
                "Jira credential appears to be expired or invalid (HTTP 401)."
            )
        elif status_code == 403:
            raise InsufficientPermissionsError(
                "Your Jira token does not have sufficient permissions (HTTP 403)."
            )
        elif status_code == 429:
            raise ConnectorValidationError(
                "Validation failed due to Jira rate-limits being exceeded."
            )
        raise UnexpectedValidationError(f"Unexpected Jira error during validation: {e}")

    # ---- Checkpoint protocol ----

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint(has_more=True)
