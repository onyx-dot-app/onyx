"""Index Jira Service Management requests and their comments.

The service desk API lists the requests and their comments, including which
comments are internal. It has no updated-since filter, so a poll uses Jira
issue search on the same project. A full run lists the service desk. Both
paths build the same document id, and the slim listing uses that same set.
"""

import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import quote

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.keys import ISSUE_KEY as _ISSUE_KEY
from onyx.connectors.jira_service_management.models import (
    CustomerComment,
    CustomerRequest,
    JsmDate,
    JsmUser,
    ServiceDesk,
)
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TabularSection,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PAGE_SIZE: int = 50
# Re-read this many requests on the next offset page so a deletion between
# two pages cannot push a live request past the page boundary.
_PAGE_OVERLAP: int = 5
_MAX_SECTION_CHARS: int = 100_000
_MAX_COMMENT_PAGES: int = 200
_MAX_PARTICIPANTS: int = 50


class JiraServiceManagementCheckpoint(ConnectorCheckpoint):
    # "requests" lists the service desk. "search" polls Jira by updated time.
    listing: str = ""
    start_at: int = 0
    next_page_token: str | None = None
    # Keys on the previous page. The next page overlaps it, and these are skipped.
    previous_keys: list[str] = []
    project_yielded: bool = False


def project_jql(
    project_key: str,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    """JQL for the service project, plus an updated window when one is set.

    The bounds are epoch milliseconds. Jira then does not read them in the
    account's time zone.
    """
    clause = f'project = "{project_key}"'
    if start is not None and start > 0:
        clause += f" AND updated >= {int(start * 1000)}"
    if end is not None:
        clause += f" AND updated <= {int(end * 1000)}"
    return clause


def plain_text(value: Any, depth: int = 0) -> str:
    """Text from a string, a Jira select value, or an Atlassian document."""
    if value is None or depth > 20:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if "<" in text and ">" in text:
            return parse_html_page_basic(text).strip()
        return text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [plain_text(item, depth + 1) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if "content" in value:
            return plain_text(value.get("content"), depth + 1)
        for key in ("text", "value", "name"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return plain_text(inner, depth + 1)
            if inner is not None and not isinstance(inner, str):
                return plain_text(inner, depth + 1)
    return ""


def _as_utc(value: JsmDate | None) -> datetime | None:
    if value is None:
        return None
    if value.epoch_millis is not None:
        return datetime.fromtimestamp(value.epoch_millis / 1000, tz=timezone.utc)
    if not value.iso8601:
        return None
    text = value.iso8601.replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", text):
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip(text: str) -> str:
    if len(text) <= _MAX_SECTION_CHARS:
        return text
    return text[:_MAX_SECTION_CHARS]


class JiraServiceManagementConnector(
    CheckpointedConnector[JiraServiceManagementCheckpoint],
    SlimConnector,
    CredentialsConnector,
):
    # A prune passes the indexing start. The slim list uses it, so requests
    # older than that start are not reported as present.
    slim_listing_honors_indexing_start = True

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        include_internal_comments: bool = True,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.project_key = project_key.strip().upper()
        self.include_internal_comments = include_internal_comments
        self._ops: JiraServiceManagementSourceOperations | None = None
        self._desk: ServiceDesk | None = None

    @property
    def ops(self) -> JiraServiceManagementSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = JiraServiceManagementSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={"jira_base_url": self.jira_base_url},
        )
        self._desk = None

    def validate_connector_settings(self) -> None:
        self.ops.get_myself()
        self._service_desk()

    def _service_desk(self) -> ServiceDesk:
        if self._desk is None:
            self._desk = self.ops.find_service_desk(project_key=self.project_key)
        return self._desk

    def doc_id(self, issue_id: str) -> str:
        """The issue id, not the key. A move between projects changes the key."""
        return f"{self.jira_base_url}/servicedesk/request/{quote(issue_id, safe='')}"

    def project_node_id(self) -> str:
        return f"{self.jira_base_url}/servicedesk/project/{self.project_key}"

    def _browse_url(self, issue_key: str) -> str:
        return f"{self.jira_base_url}/browse/{issue_key}"

    def _project_node(self, desk: ServiceDesk) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self.project_node_id(),
            raw_parent_id=None,
            display_name=desk.project_name,
            link=f"{self.jira_base_url}/browse/{desk.project_key}",
            node_type=HierarchyNodeType.PROJECT,
        )

    def _comments(self, issue_key: str) -> list[CustomerComment]:
        if _ISSUE_KEY.fullmatch(issue_key) is None:
            return []
        comments: list[CustomerComment] = []
        start = 0
        for _page in range(_MAX_COMMENT_PAGES):
            page = self.ops.list_comments(
                issue_key=issue_key, start=start, limit=_PAGE_SIZE
            )
            comments.extend(page.values)
            if _page_ends(page.is_last_page, len(page.values)):
                return comments
            start += len(page.values)
        logger.warning(
            "Stopped reading comments for %s after %s pages.",
            issue_key,
            _MAX_COMMENT_PAGES,
        )
        return comments

    def _to_document(self, request: CustomerRequest) -> Document | None:
        if (
            not request.issue_id.isdigit()
            or _ISSUE_KEY.fullmatch(request.issue_key) is None
        ):
            logger.warning("Skipping a request whose id or key is not safe to store.")
            return None
        link = self._browse_url(request.issue_key)
        summary = plain_text(request.field_text_source("summary"))
        description = plain_text(request.field_text_source("description"))
        sections: list[TextSection | ImageSection | TabularSection] = [
            TextSection(link=link, text=_clip(description))
        ]
        for comment in self._comments(request.issue_key):
            if not self.include_internal_comments and not comment.public:
                continue
            body = plain_text(comment.body)
            if not body:
                continue
            sections.append(
                TextSection(
                    link=f"{link}?focusedCommentId={quote(comment.id, safe='')}",
                    text=_clip(body),
                )
            )
        times = self.ops.get_issue_timestamps(issue_key=request.issue_key)
        created = _jira_time(times.created) or _as_utc(request.created_date)
        updated = _jira_time(times.updated)
        metadata: dict[str, str | list[str]] = {
            "project": self.project_key,
            "issue_key": request.issue_key,
        }
        if request.request_type is not None and request.request_type.name:
            metadata["request_type"] = request.request_type.name
        if request.current_status is not None and request.current_status.status:
            metadata["status"] = request.current_status.status
        if request.participants is not None:
            names = [
                name
                for user in request.participants.values[:_MAX_PARTICIPANTS]
                if (name := user.label())
            ]
            if names:
                metadata["participants"] = names
        reporter = _expert(request.reporter)
        return Document(
            id=self.doc_id(request.issue_id),
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"[{request.issue_key}] {summary}".strip(),
            title=summary or request.issue_key,
            doc_updated_at=updated,
            doc_created_at=created,
            primary_owners=[reporter] if reporter is not None else None,
            metadata=metadata,
            parent_hierarchy_raw_node_id=self.project_node_id(),
        )

    def _slim(self, request: CustomerRequest) -> SlimDocument | None:
        if (
            not request.issue_id.isdigit()
            or _ISSUE_KEY.fullmatch(request.issue_key) is None
        ):
            return None
        return SlimDocument(
            id=self.doc_id(request.issue_id),
            parent_hierarchy_raw_node_id=self.project_node_id(),
            doc_created_at=_as_utc(request.created_date),
        )

    def _fresh(
        self, requests: list[CustomerRequest], previous: set[str]
    ) -> list[CustomerRequest]:
        return [request for request in requests if request.issue_key not in previous]

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        checkpoint = checkpoint.model_copy(deep=True)
        if not checkpoint.listing:
            # A first run, and a run with no indexing start, reads the desk.
            # A later poll reads issues Jira says were updated in the window.
            checkpoint.listing = "requests" if start <= 0 else "search"
        desk = self._service_desk()
        if not checkpoint.project_yielded:
            yield self._project_node(desk)
            checkpoint.project_yielded = True
        previous = set(checkpoint.previous_keys)
        if checkpoint.listing == "requests":
            page = self.ops.list_requests(
                service_desk_id=desk.id,
                start=checkpoint.start_at,
                limit=_PAGE_SIZE,
            )
            fresh = self._fresh(page.values, previous)
            for request in fresh:
                document = self._to_document(request)
                if document is not None:
                    yield document
            keys = [request.issue_key for request in page.values]
            # A page that repeats the one before it would walk forever.
            if keys and keys == checkpoint.previous_keys:
                checkpoint.has_more = False
                return checkpoint
            checkpoint.previous_keys = keys
            checkpoint.has_more = not _page_ends(page.is_last_page, len(page.values))
            if checkpoint.has_more:
                checkpoint.start_at += _PAGE_SIZE - _PAGE_OVERLAP
            return checkpoint

        found = self.ops.search_issues(
            jql=project_jql(self.project_key, start, end),
            limit=_PAGE_SIZE,
            next_page_token=checkpoint.next_page_token,
            start_at=checkpoint.start_at,
        )
        seen = previous
        keys: list[str] = []
        for issue in found.issues:
            keys.append(issue.key)
            if issue.key in seen:
                continue
            if _ISSUE_KEY.fullmatch(issue.key) is None:
                continue
            request = self.ops.get_request(issue_key=issue.key)
            if request is None:
                continue
            document = self._to_document(request)
            if document is not None:
                yield document
        if keys and keys == checkpoint.previous_keys:
            checkpoint.has_more = False
            return checkpoint
        checkpoint.previous_keys = keys
        if found.uses_token:
            checkpoint.next_page_token = found.next_page_token
            checkpoint.has_more = not found.is_last
        else:
            checkpoint.has_more = not found.is_last and len(found.issues) >= _PAGE_SIZE
            if checkpoint.has_more:
                checkpoint.start_at += _PAGE_SIZE - _PAGE_OVERLAP
        return checkpoint

    def build_dummy_checkpoint(self) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint(has_more=True)

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint.model_validate_json(checkpoint_json)

    def _iter_all_requests(self) -> Iterator[list[CustomerRequest]]:
        desk = self._service_desk()
        start = 0
        previous: set[str] = set()
        for _page in range(100_000):
            page = self.ops.list_requests(
                service_desk_id=desk.id, start=start, limit=_PAGE_SIZE
            )
            fresh = self._fresh(page.values, previous)
            if not fresh:
                return
            yield fresh
            previous = {request.issue_key for request in page.values}
            if _page_ends(page.is_last_page, len(page.values)):
                return
            start += _PAGE_SIZE - _PAGE_OVERLAP
        raise RuntimeError(
            "Jira Service Management request list did not end after 100000 pages."
        )

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every request the index keeps.

        With no indexing start, that is the service desk. With one, it is the
        requests Jira reports as updated since that start. An auth failure
        raises, so a failed walk is not read as an empty desk.
        """
        if start is not None and start > 0:
            yield from self._slim_updated_since(start, callback)
            return
        for requests in self._iter_all_requests():
            if callback is not None and callback.should_stop():
                raise RuntimeError(
                    "Jira Service Management slim retrieval: stop signal detected"
                )
            docs = [doc for request in requests if (doc := self._slim(request))]
            if docs:
                yield cast(list[SlimDocument | HierarchyNode], docs)
            if callback is not None:
                callback.progress("jsm_slim_docs", len(docs))

    def _slim_updated_since(
        self,
        start: SecondsSinceUnixEpoch,
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """Requests updated since ``start``. The end of the window is open:
        a prune lists everything the polls since that start can index."""
        jql = project_jql(self.project_key, start, None)
        next_token: str | None = None
        start_at = 0
        previous: set[str] = set()
        for _page in range(100_000):
            if callback is not None and callback.should_stop():
                raise RuntimeError(
                    "Jira Service Management slim retrieval: stop signal detected"
                )
            found = self.ops.search_issues(
                jql=jql,
                limit=_PAGE_SIZE,
                next_page_token=next_token,
                start_at=start_at,
            )
            page_keys = {issue.key for issue in found.issues}
            if page_keys and page_keys <= previous:
                return
            docs: list[SlimDocument] = []
            for issue in found.issues:
                if issue.key in previous or _ISSUE_KEY.fullmatch(issue.key) is None:
                    continue
                request = self.ops.get_request(issue_key=issue.key)
                if request is None:
                    continue
                doc = self._slim(request)
                if doc is not None:
                    docs.append(doc)
            if docs:
                yield cast(list[SlimDocument | HierarchyNode], docs)
            if callback is not None:
                callback.progress("jsm_slim_docs", len(docs))
            previous = {issue.key for issue in found.issues}
            if found.uses_token:
                # A short Cloud page is not the last page. Jira's page size is
                # a maximum, and the token says whether another page exists.
                if found.is_last or found.next_page_token is None:
                    return
                next_token = found.next_page_token
            elif found.is_last or len(found.issues) < _PAGE_SIZE:
                return
            else:
                start_at += _PAGE_SIZE - _PAGE_OVERLAP
        raise RuntimeError(
            "Jira search did not end after 100000 pages during slim retrieval."
        )


def _jira_time(value: str | None) -> datetime | None:
    """Jira issue timestamps, for example ``2024-06-01T12:00:00.000+0000``."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", text):
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _page_ends(is_last: bool | None, count: int) -> bool:
    if count == 0 or is_last is True:
        return True
    return is_last is None and count < _PAGE_SIZE


def _expert(user: JsmUser | None) -> BasicExpertInfo | None:
    if user is None or (user.label() is None and user.email_address is None):
        return None
    return BasicExpertInfo(display_name=user.label(), email=user.email_address)
