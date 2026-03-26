"""Connector for Jira Service Management (JSM).

Indexes all tickets (requests) from a specified JSM project using the
Jira REST API and JSM Service Desk API.

Authentication is identical to the existing Jira connector:
- Cloud: email + API token
- Server/Data Center: personal access token

The connector accepts either:
- A JSM project URL  (e.g. https://example.atlassian.net/jira/servicedesk/projects/IT)
- A plain Jira base URL + project key via the jira_project field
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from jira import JIRA
from jira.exceptions import JIRAError
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
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
from onyx.connectors.jira.utils import extract_jira_project
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira_service_management.utils import build_jsm_session
from onyx.connectors.jira_service_management.utils import discover_jsm_custom_field_ids
from onyx.connectors.jira_service_management.utils import extract_jsm_metadata
from onyx.connectors.jira_service_management.utils import get_service_desks
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

_JSM_PAGE_SIZE = 50
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"
_DATE_FORMAT_ALT = "%Y-%m-%dT%H:%M:%S%z"


class JsmConnectorCheckpoint(ConnectorCheckpoint):
    offset: int = 0


def _parse_jsm_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in (_DATE_FORMAT, _DATE_FORMAT_ALT):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _build_jql(project_key: str, start_dt: datetime | None, end_dt: datetime | None) -> str:
    """Build a JQL query scoped to a single JSM project with optional time bounds."""
    parts = [f'project = "{project_key}"']
    if start_dt:
        parts.append(f'updated >= "{start_dt.strftime("%Y-%m-%d %H:%M")}"')
    if end_dt:
        parts.append(f'updated <= "{end_dt.strftime("%Y-%m-%d %H:%M")}"')
    return " AND ".join(parts) + " ORDER BY updated ASC"


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JsmConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    """Connector that indexes tickets from a Jira Service Management project.

    Credentials expected:
        jira_api_token  — API token (required)
        jira_user_email — user email for cloud instances (omit for server/DC)

    Connector-level configuration:
        jira_base_url   — base URL, e.g. https://example.atlassian.net
        jira_project    — JSM project key, e.g. IT or SD
    """

    def __init__(
        self,
        jira_base_url: str,
        jira_project: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # If jira_project looks like a full URL, extract base URL and project key from it
        if "projects" in jira_project:
            try:
                extracted_base, extracted_key = extract_jira_project(jira_project)
                jira_base_url = extracted_base
                jira_project = extracted_key
            except ValueError:
                pass  # fall through to treat it as a plain project key

        self.jira_base_url = jira_base_url.rstrip("/")
        self.jira_project = jira_project.strip().upper()
        self.comment_email_blacklist: tuple[str, ...] = tuple(
            comment_email_blacklist or []
        )
        self.batch_size = batch_size
        self._jira_client: JIRA | None = None
        self._jsm_session: requests.Session | None = None
        self._custom_field_ids: dict[str, str] = {}
        self._project_permissions_cache: dict[str, Any] = {}

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(credentials, self.jira_base_url)
        self._jsm_session = build_jsm_session(credentials)
        self._custom_field_ids = discover_jsm_custom_field_ids(self._jsm_session, self.jira_base_url)
        self._project_permissions_cache = {}
        return None

    @override
    def build_dummy_checkpoint(self) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JsmConnectorCheckpoint:
        return JsmConnectorCheckpoint.model_validate_json(checkpoint_json)

    def _iter_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
        with_perm_sync: bool,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc) if end else None

        current_offset = checkpoint.offset
        batch: list[Document | ConnectorFailure] = []

        for issue in self._fetch_issues(start_dt, end_dt, start_at=current_offset):
            doc = self._process_issue(issue)
            if doc is not None:
                if with_perm_sync:
                    doc.external_access = self._get_project_permissions(
                        self.jira_project, add_prefix=True
                    )
                batch.append(doc)
            else:
                issue_url = build_jira_url(self.jira_base_url, issue.key)
                batch.append(
                    ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=issue_url,
                            document_link=issue_url,
                        ),
                        failure_message=f"Failed to process issue {issue.key}",
                    )
                )
            current_offset += 1

            if len(batch) >= self.batch_size:
                yield batch, JsmConnectorCheckpoint(has_more=True, offset=current_offset)
                batch = []

        yield batch, JsmConnectorCheckpoint(has_more=False, offset=current_offset)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        return self._iter_checkpoint(start, end, checkpoint, with_perm_sync=False)

    def _get_project_permissions(
        self, project_key: str, add_prefix: bool = False
    ) -> Any:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        cache_key = f"{project_key}:{'prefixed' if add_prefix else 'unprefixed'}"
        if cache_key not in self._project_permissions_cache:
            self._project_permissions_cache[cache_key] = get_project_permissions(
                jira_client=self._jira_client,
                jira_project=project_key,
                add_prefix=add_prefix,
            )
        return self._project_permissions_cache[cache_key]

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        jql = f'project = "{self.jira_project}" ORDER BY updated ASC'
        try:
            results = self._jira_client.search_issues(
                jql_str=jql, startAt=0, maxResults=1
            )
            _ = len(results)  # force evaluation
        except JIRAError as e:
            status = getattr(e, "status_code", None)
            if status == 400:
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' not found or invalid. "
                    f"Ensure the project key is correct. Error: {e.text}"
                )
            elif status == 401:
                raise CredentialExpiredError(
                    "JSM credentials are expired or invalid (HTTP 401)."
                )
            elif status == 403:
                raise InsufficientPermissionsError(
                    f"Insufficient permissions to access project '{self.jira_project}'."
                )
            raise

    def _process_issue(self, issue: Any) -> Document | None:
        """Convert a Jira issue object into an Onyx Document."""
        try:
            if isinstance(issue.fields.description, str):
                description = issue.fields.description or ""
            else:
                description = extract_text_from_adf(
                    issue.raw["fields"].get("description")
                )

            comments = get_comment_strs(
                issue=issue,
                comment_email_blacklist=self.comment_email_blacklist,
            )
            ticket_content = description
            if comments:
                ticket_content += "\n" + "\n".join(
                    f"Comment: {c}" for c in comments if c
                )

            page_url = build_jira_url(self.jira_base_url, issue.key)

            metadata: dict[str, str | list[str]] = {}
            people = set()

            reporter = best_effort_get_field_from_issue(issue, "reporter")
            if reporter and (info := best_effort_basic_expert_info(reporter)):
                people.add(info)
                metadata["reporter"] = info.get_semantic_name()
                if email := info.get_email():
                    metadata["reporter_email"] = email

            assignee = best_effort_get_field_from_issue(issue, "assignee")
            if assignee and (info := best_effort_basic_expert_info(assignee)):
                people.add(info)
                metadata["assignee"] = info.get_semantic_name()
                if email := info.get_email():
                    metadata["assignee_email"] = email

            metadata["key"] = issue.key
            metadata["project"] = self.jira_project

            if priority := best_effort_get_field_from_issue(issue, "priority"):
                metadata["priority"] = priority.name
            if status := best_effort_get_field_from_issue(issue, "status"):
                metadata["status"] = status.name
            if issuetype := best_effort_get_field_from_issue(issue, "issuetype"):
                metadata["issuetype"] = issuetype.name
            if labels := best_effort_get_field_from_issue(issue, "labels"):
                metadata["labels"] = labels
            if created := best_effort_get_field_from_issue(issue, "created"):
                metadata["created"] = created
            if updated := best_effort_get_field_from_issue(issue, "updated"):
                metadata["updated"] = updated

            # JSM-specific fields
            jsm_meta = extract_jsm_metadata(issue, self._custom_field_ids)
            metadata.update(jsm_meta)

            updated_at = _parse_jsm_date(
                best_effort_get_field_from_issue(issue, "updated")
            )

            title_field = best_effort_get_field_from_issue(issue, "summary") or issue.key

            return Document(
                id=page_url,
                sections=[TextSection(link=page_url, text=ticket_content)],
                source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
                semantic_identifier=f"[{issue.key}] {title_field}",
                doc_updated_at=updated_at,
                primary_owners=list(people) if people else None,
                metadata=metadata,
            )
        except (AttributeError, KeyError, TypeError) as e:
            logger.error(f"Failed to process JSM issue {issue.key}: {e}")
            return None

    def _fetch_issues(
        self,
        start_dt: datetime | None,
        end_dt: datetime | None,
        start_at: int = 0,
    ) -> Generator[Any, None, None]:
        """Yield issues from the JSM project using JQL pagination."""
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        jql = _build_jql(self.jira_project, start_dt, end_dt)
        while True:
            try:
                issues = self._jira_client.search_issues(
                    jql_str=jql,
                    startAt=start_at,
                    maxResults=_JSM_PAGE_SIZE,
                )
            except JIRAError as e:
                status = getattr(e, "status_code", None)
                if status == 400:
                    raise ConnectorValidationError(
                        f"Invalid JQL or project not found: {jql}. Error: {getattr(e, 'text', str(e))}"
                    )
                elif status == 401:
                    raise CredentialExpiredError("JSM credentials expired (HTTP 401).")
                elif status == 403:
                    raise InsufficientPermissionsError(
                        f"Insufficient permissions for project '{self.jira_project}'."
                    )
                raise

            if not issues:
                break

            yield from issues

            if len(issues) < _JSM_PAGE_SIZE:
                break
            start_at += _JSM_PAGE_SIZE

    # -------------------------------------------------------------------------
    # CheckpointedConnectorWithPermSync
    # -------------------------------------------------------------------------

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JsmConnectorCheckpoint,
    ) -> CheckpointOutput[JsmConnectorCheckpoint]:
        return self._iter_checkpoint(start, end, checkpoint, with_perm_sync=True)

    # -------------------------------------------------------------------------
    # SlimConnectorWithPermSync
    # -------------------------------------------------------------------------

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc) if end else None

        batch: list[SlimDocument] = []
        for issue in self._fetch_issues(start_dt, end_dt):
            doc_id = build_jira_url(self.jira_base_url, issue.key)
            batch.append(
                SlimDocument(
                    id=doc_id,
                    external_access=self._get_project_permissions(
                        self.jira_project, add_prefix=False
                    ),
                )
            )
            if callback:
                if callback.should_stop():
                    return
                callback.progress("retrieve_all_slim_docs_perm_sync", 1)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    # -------------------------------------------------------------------------
    # Convenience: list all accessible service desks (used by UI validation)
    # -------------------------------------------------------------------------

    def list_service_desks(self) -> list[dict[str, Any]]:
        """Return all service desks the authenticated user can access."""
        if self._jsm_session is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return get_service_desks(self._jsm_session, self.jira_base_url)
