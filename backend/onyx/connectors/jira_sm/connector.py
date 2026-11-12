"""Jira Service Management (JSM) connector.

Pulls all tickets from a specified Jira Service Management project.
Reuses the Jira source-operations gateway and document-building utilities,
scoping queries to service-desk projects by default.
"""

import json
from collections.abc import Generator, Iterable
from datetime import datetime, timedelta
from typing import Any

from more_itertools import chunked
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
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
from onyx.connectors.jira.config import JiraConnectorConfig
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
)
from onyx.connectors.jira.utils import (
    build_jira_url,
    get_comment_strs,
    get_issue_field,
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
from onyx.connectors.source_operations import OperationConsumes, SourceOperations
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600
_JSM_PAGE_SIZE = 50


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
        project_key: str | None = None,
        jql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        include_attachments: bool = False,
    ) -> None:
        self._project_key = project_key
        self._jql_query = jql_query
        self._batch_size = batch_size
        self._include_attachments = include_attachments
        self._jira_ops: JiraSourceOperations | None = None

    # ── Credential handling ──────────────────────────────────────────

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._jira_ops = JiraSourceOperations(credentials)

    # ── JQL construction ─────────────────────────────────────────────

    def _build_jql(self, start: datetime | None = None, end: datetime | None = None) -> str:
        """Build the JQL query scoped to the JSM project."""
        clauses: list[str] = []

        if self._jql_query:
            clauses.append(f"({self._jql_query})")
        elif self._project_key:
            clauses.append(f"project = {self._project_key}")
        else:
            # Default: all open JSM requests
            clauses.append("project in (select project from project where projectType = 'service_desk')")

        if start:
            clauses.append(f"updated >= '{start.strftime('%Y-%m-%d %H:%M:%S')}'")
        if end:
            clauses.append(f"updated <= '{end.strftime('%Y-%m-%d %H:%M:%S')}'")

        return " and ".join(clauses)

    # ── Load (full index) ────────────────────────────────────────────

    @override
    def load_from_state(self) -> Generator[Iterable[Document] | CheckpointOutput, None, None]:
        if not self._jira_ops:
            raise ConnectorMissingCredentialError(self.source_type)

        jql = self._build_jql()
        logger.info(f"JSM load: JQL = {jql}")

        try:
            issue_ids = self._fetch_all_issue_ids(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            raise ConnectorFailure(f"JSM load failed: {e}")

        for batch in chunked(issue_ids, self._batch_size):
            docs = self._build_documents(batch)
            if docs:
                yield docs

    # ── Poll (incremental) ───────────────────────────────────────────

    @override
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Iterable[Document] | CheckpointOutput, None, None]:
        if not self._jira_ops:
            raise ConnectorMissingCredentialError(self.source_type)

        start_dt = datetime.fromtimestamp(start, tz=datetime.utcnow())
        end_dt = datetime.fromtimestamp(end, tz=datetime.utcnow())
        jql = self._build_jql(start=start_dt, end=end_dt)
        logger.info(f"JSM poll: JQL = {jql}")

        try:
            issue_ids = self._fetch_all_issue_ids(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            raise ConnectorFailure(f"JSM poll failed: {e}")

        for batch in chunked(issue_ids, self._batch_size):
            docs = self._build_documents(batch)
            if docs:
                yield docs

    # ── Slim (pruning / perm sync) ───────────────────────────────────

    @override
    def generate_slim_documents(self) -> Generator[GenerateSlimDocumentOutput, None, None]:
        if not self._jira_ops:
            raise ConnectorMissingCredentialError(self.source_type)

        jql = self._build_jql()
        try:
            issue_ids = self._fetch_all_issue_ids(jql)
        except JiraApiError as e:
            if e.status_code in (401, 403):
                raise CredentialExpiredError(str(e))
            raise ConnectorFailure(f"JSM slim failed: {e}")

        for batch in chunked(issue_ids, self._batch_size):
            slim_docs = []
            for issue_key in batch:
                doc_id = self._make_doc_id(issue_key)
                slim_docs.append(SlimDocument(doc_id=doc_id))
            yield GenerateSlimDocumentOutput(slim_documents=slim_docs)

    # ── Permission sync ──────────────────────────────────────────────

    @override
    def get_permissions(self, doc_id: str) -> list[str]:
        if not self._jira_ops:
            raise ConnectorMissingCredentialError(self.source_type)
        return []

    # ── Internal helpers ─────────────────────────────────────────────

    def _fetch_all_issue_ids(self, jql: str) -> list[str]:
        """Fetch all issue keys matching the JQL query."""
        assert self._jira_ops is not None
        issue_keys: list[str] = []
        start_at = 0

        while True:
            page = self._jira_ops.search_issues(jql, start=start_at, limit=_JSM_PAGE_SIZE)
            issues = page.get("issues", [])
            for issue in issues:
                key = issue.get("key")
                if key:
                    issue_keys.append(key)

            total = page.get("total", 0)
            start_at += len(issues)
            if not issues or start_at >= total:
                break

        return issue_keys

    def _build_documents(self, issue_keys: list[str]) -> list[Document]:
        """Build Document objects from a batch of issue keys."""
        assert self._jira_ops is not None
        documents: list[Document] = []

        for issue_key in issue_keys:
            try:
                issue = self._jira_ops.get_issue(issue_key)
            except JiraApiError as e:
                logger.warning(f"Failed to fetch JSM issue {issue_key}: {e}")
                continue

            doc = self._issue_to_document(issue)
            if doc:
                documents.append(doc)

        return documents

    def _issue_to_document(self, issue: dict[str, Any]) -> Document | None:
        """Convert a raw Jira issue dict into a Document."""
        key = issue.get("key", "")
        if not key:
            return None

        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        description = rich_text(fields.get("description", ""))
        status = get_named_field(fields, "status")
        priority = get_named_field(fields, "priority")
        assignee = get_named_field(fields, "assignee")
        reporter = get_named_field(fields, "reporter")
        created = fields.get("created", "")
        updated = fields.get("updated", "")
        issue_type = get_named_field(fields, "issuetype")

        # Build sections
        sections: list[TextSection] = []

        if description:
            sections.append(TextSection(text=description))

        # Add comments
        comments_raw = fields.get("comment", {})
        comments = get_comment_strs(comments_raw)
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
            source_metadata={
                "source_type": self.source_type,
                "issue_key": key,
                "url": build_jira_url(key, self._jira_ops.credentials if self._jira_ops else {}),
                **metadata,
            },
            sections=sections,
        )

    def _make_doc_id(self, issue_key: str) -> str:
        """Create a stable document ID for a JSM issue."""
        return f"jira_sm_{issue_key}"
