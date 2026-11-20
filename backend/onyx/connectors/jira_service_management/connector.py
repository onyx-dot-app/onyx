import copy
from collections.abc import Generator, Iterable
from datetime import datetime, timezone
from typing import Any

from jira import JIRA
from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.jira_service_management.utils import (
    build_jira_client,
    build_jira_url,
    extract_text_from_adf,
    get_comment_strs,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JIRA_FULL_PAGE_SIZE = 50
_JIRA_SLIM_PAGE_SIZE = 100


def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str = "*all",
) -> Iterable[Issue]:
    try:
        return jira_client.search_issues(
            jql_str=jql,
            startAt=start,
            maxResults=max_results,
            fields=fields,
        )
    except Exception as e:
        if hasattr(e, "status_code") and getattr(e, "status_code") == 401:
            raise CredentialExpiredError("Invalid Jira Service Management token") from e
        raise


def process_jira_issue(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: list[str] | None = None,
    labels_to_skip: list[str] | None = None,
) -> Document | None:
    issue_labels = set(getattr(issue.fields, "labels", None) or [])
    if labels_to_skip and issue_labels.intersection(labels_to_skip):
        return None

    raw_desc = getattr(issue.fields, "description", "")
    description = (
        raw_desc if isinstance(raw_desc, str) else extract_text_from_adf(raw_desc)
    )

    comments = get_comment_strs(
        issue, comment_email_blacklist=comment_email_blacklist
    )
    comment_block = "\n".join(f"Comment: {c}" for c in comments if c)
    content = f"{description}\n{comment_block}".strip() if comment_block else description

    page_url = build_jira_url(jira_base_url, issue.key)

    creator = getattr(issue.fields, "creator", None) or getattr(
        issue.fields, "reporter", None
    )
    primary_owners: list[BasicExpertInfo] | None = None
    if creator:
        display_name = getattr(creator, "displayName", None)
        email = getattr(creator, "emailAddress", None)
        if display_name or email:
            primary_owners = [
                BasicExpertInfo(display_name=display_name, email=email)
            ]

    metadata: dict[str, str | list[str]] = {
        "key": issue.key,
        "status": getattr(getattr(issue.fields, "status", None), "name", "N/A"),
        "project": getattr(getattr(issue.fields, "project", None), "key", "N/A"),
    }
    issue_type = getattr(getattr(issue.fields, "issuetype", None), "name", None)
    if issue_type:
        metadata["issuetype"] = issue_type
    priority = getattr(getattr(issue.fields, "priority", None), "name", None)
    if priority:
        metadata["priority"] = priority
    if issue_labels:
        metadata["labels"] = sorted(issue_labels)

    summary = getattr(issue.fields, "summary", "") or issue.key
    updated_str = getattr(issue.fields, "updated", None)

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {summary}",
        title=f"{issue.key} {summary}",
        primary_owners=primary_owners,
        doc_updated_at=time_str_to_utc(updated_str) if updated_str else None,
        metadata=metadata,
    )


class JiraServiceManagementConnectorCheckpoint(ConnectorCheckpoint):
    offset: int = 0


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraServiceManagementConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        labels_to_skip: list[str] | None = None,
        jql_query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        scoped_token: bool = False,
        **kwargs: Any,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = project_key
        self.comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = (
            labels_to_skip
            if labels_to_skip is not None
            else JIRA_CONNECTOR_LABELS_TO_SKIP
        )
        self.jql_query = jql_query
        self.batch_size = batch_size or _JIRA_FULL_PAGE_SIZE
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._jira_client = build_jira_client(
            credentials,
            self.jira_base,
            scoped_token=self.scoped_token,
        )

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        clauses: list[str] = []
        if self.jql_query:
            clauses.append(f"({self.jql_query})")
        elif self.project_key:
            clauses.append(f'project = "{self.project_key}"')

        if start is not None:
            start_date = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )
            clauses.append(f"updated >= '{start_date}'")
        if end is not None:
            end_date = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )
            clauses.append(f"updated <= '{end_date}'")

        return " AND ".join(clauses)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementConnectorCheckpoint]:
        return self.load_from_checkpoint_with_perm_sync(start, end, checkpoint)

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementConnectorCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementConnectorCheckpoint]:
        jql = self._build_jql(start=start, end=end)
        page_size = self.batch_size or _JIRA_FULL_PAGE_SIZE

        current_offset = checkpoint.offset
        issues = list(
            _perform_jql_search(
                self.jira_client,
                jql,
                current_offset,
                page_size,
            )
        )

        for issue in issues:
            doc = process_jira_issue(
                self.jira_base,
                issue,
                comment_email_blacklist=self.comment_email_blacklist,
                labels_to_skip=self.labels_to_skip,
            )
            if doc is not None:
                yield doc
            current_offset += 1

        new_checkpoint = copy.deepcopy(checkpoint)
        new_checkpoint.offset = current_offset
        new_checkpoint.has_more = len(issues) >= page_size
        return new_checkpoint

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Generator[list[SlimDocument], None, None]:
        jql = self._build_jql(start=start, end=end)
        offset = 0
        while True:
            issues = list(
                _perform_jql_search(
                    self.jira_client,
                    jql,
                    offset,
                    _JIRA_SLIM_PAGE_SIZE,
                    fields="key,labels",
                )
            )
            if not issues:
                break

            slim_batch: list[SlimDocument] = []
            for issue in issues:
                issue_labels = set(getattr(issue.fields, "labels", None) or [])
                if self.labels_to_skip and issue_labels.intersection(
                    self.labels_to_skip
                ):
                    continue
                slim_batch.append(
                    SlimDocument(
                        id=build_jira_url(self.jira_base, issue.key),
                        perm_sync_data=None,
                    )
                )

            if slim_batch:
                yield slim_batch

            if len(issues) < _JIRA_SLIM_PAGE_SIZE:
                break
            offset += len(issues)

    @override
    def build_dummy_checkpoint(self) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint(has_more=True)

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        self.jira_client.projects()

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint.model_validate_json(
            checkpoint_json
        )
