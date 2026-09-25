"""Connector for Jira Service Management projects."""

from typing import Any, ClassVar
from urllib.parse import quote

from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, process_jira_issue
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_COMMENT_PAGE_SIZE = 50
_JSM_COMMENT_API_BASE = "{server}/rest/servicedeskapi/{path}"


class JiraServiceManagementConnector(JiraConnector):
    """Index tickets from one service desk project.

    The connector reuses Jira's checkpoint, document, and permission-sync
    behavior. It reads comments from the JSM API with an explicit public-only
    filter so internal notes are never indexed by default.
    """

    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Keep custom filters inside the configured service desk project."""
        if not self.jira_project:
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )

        time_filter = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        project_filter = f"project = {self.quoted_jira_project}"
        if self.jql_query:
            return f"{project_filter} AND ({self.jql_query}) AND {time_filter}"
        return f"{project_filter} AND {time_filter}"

    def _get_public_comment_texts(self, issue: Issue) -> list[str]:
        """Read public comments from the JSM API, with strict fallback parsing."""
        try:
            return self._fetch_public_comment_texts(issue)
        except Exception:
            logger.exception(
                "Could not read JSM comments for %s; using only comments marked public.",
                issue.key,
            )
            return self._get_flagged_public_comment_texts(issue)

    def _fetch_public_comment_texts(self, issue: Issue) -> list[str]:
        comments: list[str] = []
        start = 0
        while True:
            page = self.jira_client._get_json(
                path=f"request/{quote(issue.key, safe='')}/comment",
                params={
                    "public": True,
                    "start": start,
                    "limit": _JSM_COMMENT_PAGE_SIZE,
                },
                base=_JSM_COMMENT_API_BASE,
            )
            if not isinstance(page, dict):
                raise ValueError("JSM comment response must be an object")

            values = page.get("values")
            if not isinstance(values, list):
                raise ValueError("JSM comment response is missing its values list")

            for comment in values:
                if not isinstance(comment, dict) or comment.get("public") is not True:
                    continue

                author = comment.get("author")
                email = author.get("emailAddress") if isinstance(author, dict) else None
                if email in self.comment_email_blacklist:
                    continue

                body = comment.get("body")
                if isinstance(body, str):
                    text = body
                elif isinstance(body, dict):
                    text = extract_text_from_adf(body)
                else:
                    continue

                if text.strip():
                    comments.append(text)

            if page.get("isLastPage") is True or not values:
                return comments

            next_start = start + len(values)
            if next_start <= start:
                raise ValueError("JSM comment pagination did not advance")
            start = next_start

    def _get_flagged_public_comment_texts(self, issue: Issue) -> list[str]:
        """Fallback for Jira deployments that do not expose the JSM API."""
        result: list[str] = []
        try:
            issue_comments = issue.fields.comment.comments
        except (AttributeError, TypeError):
            return result

        for comment in issue_comments:
            try:
                raw_comment = comment.raw
                if (
                    not isinstance(raw_comment, dict)
                    or raw_comment.get("jsdPublic") is not True
                ):
                    continue

                author = comment.author
                email = author.emailAddress if author is not None else None
                if email in self.comment_email_blacklist:
                    continue

                body = comment.body
                if isinstance(body, str) and body.strip():
                    result.append(body)
                elif isinstance(body, dict):
                    text = extract_text_from_adf(body)
                    if text.strip():
                        result.append(text)
            except (AttributeError, KeyError, TypeError):
                logger.warning("Skipping malformed JSM comment on %s", issue.key)
        return result

    def _process_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        return process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            preloaded_comment_texts=self._get_public_comment_texts(issue),
            source=self.document_source,
        )

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        if not self.jira_project or not self.jira_project.strip():
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )

        try:
            project = self.jira_client.project(self.jira_project)
        except Exception as error:
            self._handle_jira_connector_settings_error(error)
            raise

        project_type: Any = project.raw.get("projectTypeKey")
        if isinstance(project_type, str) and project_type != "service_desk":
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is not a Jira Service Management project."
            )

        if self.jql_query:
            super().validate_connector_settings()
