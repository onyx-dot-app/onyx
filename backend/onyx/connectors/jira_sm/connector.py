"""Jira Service Management (JSM) connector.

Pulls all tickets from a specified Jira Service Management project.
Reuses the Jira source-operations gateway and document-building utilities,
scoping queries to service-desk projects by default.
"""

from collections.abc import Generator, Iterable
from datetime import datetime, timezone
from typing import Any

from more_itertools import chunked
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.atlassian_query import has_order_by
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
    is_cloud_gateway,
)
from onyx.connectors.jira.utils import (
    build_jira_url,
    get_comment_strs,
    get_named_field,
    rich_text,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600
_JSM_PAGE_SIZE = 50

JSM_ORDER_BY_ERROR = (
    "Unsupported clause: ORDER BY. Jira does not allow it inside the sync filter."
)


class JiraSmConnector(
    CheckpointedConnectorWithPermSync,
    SlimConnectorWithPermSync,
):
    """Connector for Jira Service Management (JSM) projects.

    Indexes all tickets (requests and tasks) from a JSM project,
    including descriptions, comments, and attachments.
    """

    source_type = DocumentSource.JIRA_SM

    def __init__(
        self,
        jira_base_url: str = "",
        project_key: str | None = None,
        jql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        include_attachments: bool = False,
        scoped_token: bool = False,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/") if jira_base_url else ""
        self.jira_project = (project_key or "").strip() or None
        self.jql_query = (jql_query or "").strip() or None
        self._batch_size = batch_size
        self._include_attachments = include_attachments
        self.scoped_token = scoped_token
        self._source_operations: JiraSourceOperations | None = None

    # ── Credential handling ──────────────────────────────────────────

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._source_operations = JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA_SM.value, credentials
            ),
            connector_specific_config={
                "jira_base_url": self.jira_base,
                "scoped_token": self.scoped_token,
            },
        )
        return None

    @property
    def source_operations(self) -> JiraSourceOperations:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError(self.source_type)
        return self._source_operations

    # ── JQL construction ─────────────────────────────────────────────

    def _build_jql(self, start: datetime | None = None, end: datetime | None = None) -> str:
        """Build the JQL query scoped to the JSM project."""
        clauses: list[str] = []

        if self.jql_query:
            if has_order_by(self.jql_query):
                raise ConnectorValidationError(JSM_ORDER_BY_ERROR)
            clauses.append(f"({self.jql_query})")
        elif self.jira_project:
            clauses.append(f"project = {self.jira_project}")
        else:
            # Default: restrict to service-desk (JSM) projects only
            clauses.append("project in (select projectkey from "com.atlassian.jira.project.type" where type = 'service_desk')")

        if start:
            clauses.append(f"updated >= '{start.strftime('%Y-%m-%d %H:%M:%S')}'")
        if end:
            clauses.append(f"updated <= '{end.strftime('%Y-%m-%d %H:%M:%S')}'")

        return " and ".join(clauses)

    # ── Load (full index) ────────────────────────────────────────────

    @override
    def load_from_state(self) -> Generator[Iterable[Document] | CheckpointOutput, None, None]:
        jql = self._build_jql()
        logger.info(f"JSM load: JQL = {jql}")

        try:
            issue_keys = self._fetch_all_issue_keys(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            yield ConnectorFailure(
                failure_message=f"JSM load failed: {e}",
                connector_id=None,
            )
            return

        for batch in chunked(issue_keys, self._batch_size):
            docs = self._build_documents(batch)
            if docs:
                yield docs

    # ── Poll (incremental) ───────────────────────────────────────────

    @override
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Iterable[Document] | CheckpointOutput, None, None]:
        # Jira interprets JQL dates in the site's configured timezone.
        # We pass naive local-time strings; Jira resolves them server-side.
        start_dt = datetime.fromtimestamp(start)
        end_dt = datetime.fromtimestamp(end)
        jql = self._build_jql(start=start_dt, end=end_dt)
        logger.info(f"JSM poll: JQL = {jql}")

        try:
            issue_keys = self._fetch_all_issue_keys(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            yield ConnectorFailure(
                failure_message=f"JSM poll failed: {e}",
                connector_id=None,
            )
            return

        for batch in chunked(issue_keys, self._batch_size):
            docs = self._build_documents(batch)
            if docs:
                yield docs

    # ── Checkpoint + PermSync ────────────────────────────────────────

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint | None,
    ) -> Generator[Iterable[Document] | CheckpointOutput, None, None]:
        # JSM does not support incremental checkpointing; do a full load.
        yield from self.load_from_state()

    # ── Slim (pruning / perm sync) ───────────────────────────────────

    @override
    def generate_slim_documents(self) -> GenerateSlimDocumentOutput:
        jql = self._build_jql()
        try:
            issue_keys = self._fetch_all_issue_keys(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            raise

        for batch in chunked(issue_keys, self._batch_size):
            yield [SlimDocument(id=self._make_doc_id(key)) for key in batch]

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self.generate_slim_documents()

    # ── Permission sync ──────────────────────────────────────────────

    @override
    def get_permissions(self, doc_id: str) -> list[str]:
        return []

    # ── Internal helpers ─────────────────────────────────────────────

    def _fetch_all_issue_keys(self, jql: str) -> list[str]:
        """Fetch all issue keys matching the JQL query."""
        ops = self.source_operations
        issue_keys: list[str] = []

        if is_cloud_gateway(ops):
            # Cloud: use enhanced JQL search (search_issue_ids) + bulk fetch
            next_page_token: str | None = None
            all_ids: list[str] = []
            while True:
                page: JiraIssueIdPage = ops.search_issue_ids(
                    jql=jql,
                    next_page_token=next_page_token,
                    max_results=_JSM_PAGE_SIZE,
                )
                all_ids.extend(page.issue_ids)
                next_page_token = page.next_page_token
                if not next_page_token:
                    break

            # Convert numeric IDs to keys via bulk fetch
            for id_batch in chunked(all_ids, 100):
                issues = ops.bulk_fetch_issues(issue_ids=list(id_batch))
                for issue in issues:
                    key = issue.get("key")
                    if key:
                        issue_keys.append(key)
        else:
            # Server / Data Center: use offset-based search_issues
            start_at = 0
            while True:
                issues = ops.search_issues(
                    jql=jql,
                    start_at=start_at,
                    max_results=_JSM_PAGE_SIZE,
                )
                for issue in issues:
                    key = issue.get("key")
                    if key:
                        issue_keys.append(key)
                start_at += len(issues)
                if not issues:
                    break

        return issue_keys

    def _build_documents(self, issue_keys: list[str]) -> list[Document]:
        """Build Document objects from a batch of issue keys."""
        ops = self.source_operations
        documents: list[Document] = []

        # Fetch full issue data
        if is_cloud_gateway(ops):
            # Cloud: need to fetch by ID, so we re-search to get full issues
            # For simplicity, use search_issues with a key-based JQL
            for issue_key in issue_keys:
                try:
                    issues = ops.search_issues(
                        jql=f"key = {issue_key}",
                        start_at=0,
                        max_results=1,
                    )
                    if issues:
                        doc = self._issue_to_document(issues[0])
                        if doc:
                            documents.append(doc)
                except JiraApiError as e:
                    logger.warning(f"Failed to fetch JSM issue {issue_key}: {e}")
        else:
            # Server: search_issues returns full issues
            for issue_key in issue_keys:
                try:
                    issues = ops.search_issues(
                        jql=f"key = {issue_key}",
                        start_at=0,
                        max_results=1,
                    )
                    if issues:
                        doc = self._issue_to_document(issues[0])
                        if doc:
                            documents.append(doc)
                except JiraApiError as e:
                    logger.warning(f"Failed to fetch JSM issue {issue_key}: {e}")

        return documents

    def _issue_to_document(self, issue: dict[str, Any]) -> Document | None:
        """Convert a raw Jira issue dict into a Document."""
        key = issue.get("key", "")
        if not key:
            return None

        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        description = rich_text(fields.get("description", ""))
        status = get_named_field(issue, "status")
        priority = get_named_field(issue, "priority")
        assignee = get_named_field(issue, "assignee")
        reporter = get_named_field(issue, "reporter")
        created = fields.get("created", "")
        updated = fields.get("updated", "")
        issue_type = get_named_field(issue, "issuetype")

        # Build sections
        sections: list[TextSection] = []

        if description:
            sections.append(TextSection(text=description))

        # Add comments
        comments_raw = fields.get("comment", {})
        comments = get_comment_strs(issue)
        for comment in comments:
            sections.append(TextSection(text=comment))

        # Build metadata
        metadata: dict[str, Any] = {
            "status": status,
            "priority": priority,
            "assignee": assignee,
            "reporter": reporter,
            "issue_type": issue_type,
            "created": created,
            "updated": updated,
        }

        doc_id = self._make_doc_id(key)
        title = f"[{key}] {summary}"

        return Document(
            id=doc_id,
            name=title,
            body=summary + "\n\n" + "\n\n".join(s.text for s in sections),
            doc_type="jira_sm_ticket",
            source=self.source_type,
            source_metadata={
                "source_type": self.source_type,
                "issue_key": key,
                "url": build_jira_url(self.jira_base, key),
                **metadata,
            },
            sections=sections,
        )

    def _make_doc_id(self, issue_key: str) -> str:
        """Create a stable document ID for a JSM issue, including site for uniqueness."""
        site = self.jira_base.replace("https://", "").replace("http://", "")
        return f"jira_sm_{site}_{issue_key}"
