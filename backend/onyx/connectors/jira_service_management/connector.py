"""
Jira Service Management (JSM) Connector for Onyx.

Fetches tickets (Service Requests, Incidents, Problems, Changes) from a
specified JSM project using the Jira REST API v2.

Credentials required:
  - jira_user_email   : Atlassian account e-mail
  - jira_api_token    : Atlassian API token  (https://id.atlassian.com/manage/api-tokens)
  - jira_base_url     : e.g. https://yourcompany.atlassian.net
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Generator

from jira import JIRA, JIRAError

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    CheckpointConnector,
    CheckpointOutput,
    ConnectorCheckpoint,
    ConnectorFailure,
    CredentialedConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    Section,
)

logger = logging.getLogger(__name__)

# JSM issue types we want to index
JSM_ISSUE_TYPES = ("Service Request", "Incident", "Problem", "Change", "Service Task")

# Jira date format
JIRA_DATE_FMT = "%Y-%m-%d %H:%M"


def _build_jsm_jql(
    project_key: str,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    issue_type_filter = ", ".join(f'"{t}"' for t in JSM_ISSUE_TYPES)
    jql = f'project = "{project_key}" AND issuetype in ({issue_type_filter})'

    if start is not None:
        start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(JIRA_DATE_FMT)
        jql += f' AND updated >= "{start_str}"'

    if end is not None:
        end_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(JIRA_DATE_FMT)
        jql += f' AND updated <= "{end_str}"'

    jql += " ORDER BY updated ASC"
    return jql


def _issue_to_document(issue: Any, jira_base_url: str) -> Document:
    """Convert a jira.Issue object into an Onyx Document."""
    fields = issue.fields

    # ----- text content -----
    summary = fields.summary or ""
    description = fields.description or ""

    # Include comments
    comment_texts: list[str] = []
    try:
        for comment in fields.comment.comments:
            author = getattr(comment.author, "displayName", "Unknown")
            body = comment.body or ""
            comment_texts.append(f"[{author}]: {body}")
    except Exception:
        pass

    full_text = "\n\n".join(filter(None, [summary, description] + comment_texts))

    # ----- metadata -----
    issue_url = f"{jira_base_url.rstrip('/')}/browse/{issue.key}"
    status = getattr(fields.status, "name", "Unknown")
    priority = getattr(fields.priority, "name", None) if fields.priority else None
    issue_type = getattr(fields.issuetype, "name", "Unknown")

    assignee_name = (
        fields.assignee.displayName if fields.assignee else None
    )
    reporter_name = (
        fields.reporter.displayName if fields.reporter else None
    )

    experts: list[BasicExpertInfo] = []
    if assignee_name:
        experts.append(BasicExpertInfo(display_name=assignee_name))
    if reporter_name and reporter_name != assignee_name:
        experts.append(BasicExpertInfo(display_name=reporter_name))

    metadata: dict[str, str | list[str]] = {
        "issue_key": issue.key,
        "issue_type": issue_type,
        "status": status,
    }
    if priority:
        metadata["priority"] = priority

    # Parse updated time
    updated_at: datetime | None = None
    try:
        updated_at = datetime.strptime(
            fields.updated[:19], "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except Exception:
        pass

    return Document(
        id=f"jsm:{issue.key}",
        sections=[Section(link=issue_url, text=full_text)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {summary}",
        doc_updated_at=updated_at,
        primary_owners=experts,
        metadata=metadata,
        title=f"{issue.key}: {summary}",
    )


class JiraServiceManagementConnector(CheckpointConnector, CredentialedConnector):
    """
    Connector that indexes JSM tickets from a single Jira Service Management project.

    Config args (set in Admin UI):
        jira_base_url  : e.g. https://yourcompany.atlassian.net
        project_key    : JSM project key, e.g. "IT" or "HELPDESK"

    Credentials (stored as connector credential):
        jira_user_email : your Atlassian email
        jira_api_token  : Atlassian API token
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.project_key = project_key.strip()
        self.batch_size = batch_size
        self._jira_client: JIRA | None = None

    # ------------------------------------------------------------------
    # CredentialedConnector
    # ------------------------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        email = credentials.get("jira_user_email")
        token = credentials.get("jira_api_token")
        if not email or not token:
            raise ConnectorMissingCredentialError(
                "jira_user_email and jira_api_token are required."
            )
        self._jira_client = JIRA(
            server=self.jira_base_url,
            basic_auth=(email, token),
        )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError(
                "load_credentials() must be called before indexing."
            )
        return self._jira_client

    def _fetch_batch(
        self,
        jql: str,
        start_at: int,
    ) -> tuple[list[Document], bool]:
        """
        Fetch one page of issues. Returns (documents, has_more).
        """
        try:
            issues = self._client.search_issues(
                jql,
                startAt=start_at,
                maxResults=self.batch_size,
                fields="*all",
            )
        except JIRAError as e:
            logger.error(f"JSM connector JQL error: {e.text} | JQL: {jql}")
            raise

        docs: list[Document] = []
        for issue in issues:
            try:
                docs.append(_issue_to_document(issue, self.jira_base_url))
            except Exception as exc:
                logger.warning(f"Failed to process JSM issue {issue.key}: {exc}")

        has_more = (start_at + len(issues)) < issues.total
        return docs, has_more

    # ------------------------------------------------------------------
    # CheckpointConnector
    # ------------------------------------------------------------------

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput:
        """
        Incrementally fetch JSM issues updated between *start* and *end*.
        The checkpoint stores the current pagination offset.
        """
        jql = _build_jsm_jql(self.project_key, start=start, end=end)
        start_at: int = checkpoint.get("start_at", 0) if checkpoint else 0

        while True:
            docs, has_more = self._fetch_batch(jql, start_at)

            if docs:
                yield docs

            start_at += len(docs)

            if not has_more:
                break

            yield ConnectorCheckpoint({"start_at": start_at})

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint({"start_at": 0})

    def validate_checkpoint_json(self, checkpoint_json: dict[str, Any]) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(checkpoint_json)
