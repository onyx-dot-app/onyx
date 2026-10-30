"""Jira Service Management connector.

A service desk is a Jira project. The Service Desk API identifies the desk and
its project; the project's issues are the tickets. This connector resolves the
configured desks to project keys, then uses the existing Jira search, bulk
fetch and parser. Indexing, polling and pruning therefore select the same
tickets, and the Jira parsing rules stay in one place.

Cloud only: the ticket fetch uses the Jira Cloud bulk-fetch endpoint, which
Server / Data Center does not have. A Data Center credential is rejected with
a clear validation error instead of indexing incomplete data.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator
from typing import Any, TypeVar

import requests

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    REQUEST_TIMEOUT_SECONDS,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira.connector import (
    build_jira_ticket_content,
    jira_issue_skip_reason,
    process_jira_issue,
)
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The Service Desk API caps a page at 100; 50 keeps a failed page cheap to retry.
_JSM_PAGE_LIMIT = 50
# A repeated page without a completion marker is a provider bug, not a reason
# to loop forever.
_JSM_MAX_PAGES = 10_000
# Jira's bulk-fetch endpoint accepts at most 100 issue ids per request.
_BULK_FETCH_LIMIT = 100

_Item = TypeVar("_Item")


def _chunks(items: Iterable[_Item], size: int) -> Iterator[list[_Item]]:
    chunk: list[_Item] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    """Indexes the tickets of one or more Jira Service Management desks."""

    def __init__(
        self,
        jira_base_url: str,
        service_desk_ids: list[str] | None = None,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        scoped_token: bool = False,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        # Blank scope fields mean "not set", as on the create form.
        self.service_desk_ids = (
            [
                str(desk_id).strip()
                for desk_id in service_desk_ids
                if str(desk_id).strip()
            ]
            if service_desk_ids
            else None
        )
        self.project_key = (project_key or "").strip().upper() or None
        self._comment_email_blacklist = comment_email_blacklist or []
        self.batch_size = batch_size
        self.labels_to_skip = set(labels_to_skip)
        self.scoped_token = scoped_token

        self._source_operations: JiraSourceOperations | None = None
        self._session = requests.Session()
        self._service_desk_base_url: str | None = None

    @property
    def comment_email_blacklist(self) -> tuple[str, ...]:
        return tuple(
            email.strip() for email in self._comment_email_blacklist if email.strip()
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = credentials.get("jira_api_token")
        if not api_token:
            raise ConnectorMissingCredentialError("Jira Service Management")

        email = credentials.get("jira_user_email") or None
        if not email:
            raise ConnectorValidationError(
                "Jira Service Management needs a Jira Cloud credential with an "
                "account email. Data Center personal access tokens are not "
                "supported by the ticket fetch."
            )

        self._session = requests.Session()
        self._session.auth = (email, api_token)
        self._source_operations = JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA.value, credentials
            ),
            connector_specific_config={
                "jira_base_url": self.jira_base,
                "scoped_token": self.scoped_token,
            },
        )
        self._service_desk_base_url = self._resolve_service_desk_base()
        return None

    def _resolve_service_desk_base(self) -> str:
        if not self.scoped_token:
            return self.jira_base
        try:
            return scoped_url(self.jira_base, "jira")
        except Exception as e:
            raise ConnectorValidationError(
                "Could not resolve the Atlassian cloud id for the scoped token."
            ) from e

    def _service_desk_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._source_operations is None or self._service_desk_base_url is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        url = f"{self._service_desk_base_url}/rest/servicedeskapi/{path.lstrip('/')}"
        try:
            response = self._session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise UnexpectedValidationError(
                "Jira Service Management request failed."
            ) from e

        status = response.status_code
        if status == 401:
            raise CredentialExpiredError(
                "Invalid or expired Jira Service Management credentials (HTTP 401)."
            )
        if status == 403:
            raise InsufficientPermissionsError(
                "The Jira credential cannot read this service desk (HTTP 403)."
            )
        if status == 404:
            raise ConnectorValidationError(
                "Jira Service Management resource not found (HTTP 404)."
            )
        if status == 429:
            raise RateLimitedValidationError(
                "Jira Service Management rate limit exceeded (HTTP 429)."
            )
        if not 200 <= status < 300:
            raise UnexpectedValidationError(
                f"Jira Service Management returned HTTP {status}."
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise UnexpectedValidationError(
                "Jira Service Management returned invalid JSON."
            ) from e
        if not isinstance(payload, dict):
            raise UnexpectedValidationError(
                "Jira Service Management returned an invalid payload."
            )
        return payload

    def _paginate_desks(self) -> Iterator[dict[str, Any]]:
        """Follows ``start``/``isLastPage`` until the provider says it is done."""
        start = 0
        seen: set[str] = set()
        for _ in range(_JSM_MAX_PAGES):
            payload = self._service_desk_get(
                "servicedesk", {"start": start, "limit": _JSM_PAGE_LIMIT}
            )
            values = payload.get("values")
            if not isinstance(values, list) or any(
                not isinstance(value, dict) for value in values
            ):
                raise UnexpectedValidationError(
                    "Jira Service Management returned an invalid page."
                )

            if not values:
                if payload.get("isLastPage") is True:
                    return
                raise UnexpectedValidationError(
                    "Jira Service Management returned an empty page without a "
                    "completion marker."
                )

            for value in values:
                desk_id = str(value.get("id") or "").strip()
                if not desk_id:
                    raise UnexpectedValidationError(
                        "Jira Service Management returned a service desk without an id."
                    )
                if desk_id in seen:
                    raise UnexpectedValidationError(
                        "Jira Service Management repeated a service desk in a page."
                    )
                seen.add(desk_id)
                yield value

            if payload.get("isLastPage") is True:
                return
            start += len(values)

        raise UnexpectedValidationError(
            "Jira Service Management did not finish paginating."
        )

    def _list_service_desks(self) -> list[dict[str, Any]]:
        desks = list(self._paginate_desks())
        if self.service_desk_ids is not None:
            visible_ids = {str(desk.get("id") or "").strip() for desk in desks}
            missing = [
                desk_id
                for desk_id in self.service_desk_ids
                if desk_id not in visible_ids
            ]
            if missing:
                raise ConnectorValidationError(
                    "Jira Service Management cannot see the configured service "
                    f"desk id(s): {', '.join(missing)}. Check the ids and the "
                    "connector account's service desk access."
                )
        filtered: list[dict[str, Any]] = []
        for desk in desks:
            desk_id = str(desk.get("id") or "").strip()
            project_key = str(desk.get("projectKey") or "").strip().upper()
            if (
                self.service_desk_ids is not None
                and desk_id not in self.service_desk_ids
            ):
                continue
            if self.project_key is not None and project_key != self.project_key:
                continue
            filtered.append(desk)
        return filtered

    def _desks_or_raise(self) -> list[dict[str, Any]]:
        desks = self._list_service_desks()
        if not desks:
            scope = self.project_key or self.service_desk_ids or "all visible desks"
            raise ConnectorValidationError(
                f"No Jira Service Management service desk is visible for scope "
                f"{scope!r}."
            )
        return desks

    @staticmethod
    def _desk_by_project(desks: list[dict[str, Any]]) -> dict[str, str]:
        """Maps a Jira project key to its first service desk id."""
        mapping: dict[str, str] = {}
        for desk in desks:
            project_key = str(desk.get("projectKey") or "").strip().upper()
            desk_id = str(desk.get("id") or "").strip()
            if not project_key or not desk_id:
                raise UnexpectedValidationError(
                    "Jira Service Management returned a service desk without a "
                    "project key."
                )
            mapping.setdefault(project_key, desk_id)
        if not mapping:
            raise ConnectorValidationError(
                "The selected Jira Service Management desks have no project key."
            )
        return mapping

    @staticmethod
    def _project_jql(project_keys: Iterable[str]) -> str:
        quoted = ", ".join(f'"{key}"' for key in sorted(set(project_keys)))
        return f"project in ({quoted})"

    def _iter_issue_ids(self, jql: str) -> Iterator[str]:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        token: str | None = None
        seen_tokens: set[str] = set()
        for _ in range(_JSM_MAX_PAGES):
            page = self._source_operations.search_issue_ids(
                jql=jql, next_page_token=token
            )
            yield from page.issue_ids
            token = page.next_page_token
            if not token:
                return
            if token in seen_tokens:
                raise UnexpectedValidationError(
                    "Jira Service Management repeated its search cursor."
                )
            seen_tokens.add(token)

        raise UnexpectedValidationError(
            "Jira Service Management did not finish searching."
        )

    def _fetch_issues(self, issue_ids: list[str]) -> list[dict[str, Any]]:
        if not issue_ids:
            return []
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._source_operations.bulk_fetch_issues(
            issue_ids=issue_ids, raise_on_missing=True
        )

    def _documents(
        self,
        issues: list[dict[str, Any]],
        desk_by_project: dict[str, str],
    ) -> Generator[Document, None, None]:
        for issue in issues:
            document = process_jira_issue(
                jira_base_url=self.jira_base,
                issue=issue,
                comment_email_blacklist=self.comment_email_blacklist,
                labels_to_skip=self.labels_to_skip,
            )
            if document is None:
                continue
            project = (issue.get("fields") or {}).get("project") or {}
            project_key = str(project.get("key") or "").upper()
            metadata = dict(document.metadata or {})
            desk_id = desk_by_project.get(project_key)
            if desk_id:
                metadata["jsm_service_desk_id"] = desk_id
            # The ticket text is Jira-shaped; the source is what tells Onyx
            # which connector owns it.
            yield document.model_copy(
                update={
                    "source": DocumentSource.JIRA_SERVICE_MANAGEMENT,
                    "metadata": metadata,
                }
            )

    def _documents_for_jql(
        self, jql: str, desk_by_project: dict[str, str]
    ) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for issue_ids in _chunks(self._iter_issue_ids(jql), _BULK_FETCH_LIMIT):
            issues = self._fetch_issues(issue_ids)
            for document in self._documents(issues, desk_by_project):
                batch.append(document)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        desks = self._desks_or_raise()
        desk_by_project = self._desk_by_project(desks)
        yield from self._documents_for_jql(
            self._project_jql(desk_by_project), desk_by_project
        )

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        desks = self._desks_or_raise()
        desk_by_project = self._desk_by_project(desks)
        window = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        yield from self._documents_for_jql(
            f"{self._project_jql(desk_by_project)} AND {window}", desk_by_project
        )

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        desks = self._desks_or_raise()
        desk_by_project = self._desk_by_project(desks)
        # Desk access, Jira search and issue fetch use different permissions
        # and scopes, so all are checked. One result bounds the check; 0 is a
        # valid answer for an empty project.
        page = self._source_operations.search_issue_ids(
            jql=self._project_jql(desk_by_project), max_results=1, fast=True
        )
        issue_ids = page.issue_ids
        if not issue_ids:
            # An empty scope would otherwise leave issue-fetch permission
            # untested. Any readable ticket proves the endpoint works; it is
            # fetched for the check only and never indexed.
            accessible = self._source_operations.search_issue_ids(
                jql="created >= 1970-01-01", max_results=1, fast=True
            )
            issue_ids = accessible.issue_ids
        if issue_ids:
            self._source_operations.bulk_fetch_issues(
                issue_ids=issue_ids, raise_on_missing=True, fast=True
            )

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # Slim and full indexing share the project scope, so pruning removes
        # exactly the tickets that left that scope.
        del start, end, callback
        desks = self._desks_or_raise()
        desk_by_project = self._desk_by_project(desks)
        batch: list[SlimDocument | HierarchyNode] = []
        for issue_ids in _chunks(
            self._iter_issue_ids(self._project_jql(desk_by_project)),
            _BULK_FETCH_LIMIT,
        ):
            issues = self._fetch_issues(issue_ids)
            for issue in issues:
                issue_key = str(issue.get("key") or "").strip()
                if not issue_key:
                    raise UnexpectedValidationError(
                        "Jira returned a ticket without a key."
                    )
                ticket_content = build_jira_ticket_content(
                    issue, comment_email_blacklist=self.comment_email_blacklist
                )
                skip_reason = jira_issue_skip_reason(
                    issue, ticket_content, labels_to_skip=self.labels_to_skip
                )
                if skip_reason is not None:
                    logger.info("Skipping %s because %s.", issue_key, skip_reason)
                    continue
                batch.append(SlimDocument(id=build_jira_url(self.jira_base, issue_key)))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


__all__ = ["JiraServiceManagementConnector"]
