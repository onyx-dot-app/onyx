from datetime import datetime
from datetime import timezone
from typing import Any

from jira import JIRA
from jira.resources import Issue

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_ISSUE_TYPES = (
    '"Service Request"',
    '"Incident"',
    '"Problem"',
    '"Change"',
    '"Service Task"',
)


class JiraServiceManagementCheckpoint(ConnectorCheckpoint):
    start_at: int = 0
    has_more: bool = True


def _process_jsm_issue(
    jira_base_url: str,
    issue: Issue,
) -> Document | None:
    page_url = build_jira_url(jira_base_url, issue.key)

    # Build ticket content from summary + description + comments
    summary = getattr(issue.fields, "summary", "") or ""
    description = getattr(issue.fields, "description", "") or ""
    if isinstance(description, dict):
        description = extract_text_from_adf(description)

    comment_strs = []
    try:
        comment_strs = get_comment_strs(issue)
    except Exception:
        pass

    ticket_content = summary
    if description:
        ticket_content += f"\n\n{description}"
    if comment_strs:
        ticket_content += "\n\n" + "\n\n".join(comment_strs)

    if not ticket_content.strip():
        return None

    metadata: dict[str, str | list[str]] = {}
    metadata["issue_key"] = issue.key

    status = best_effort_get_field_from_issue(issue, "status")
    if status is not None:
        metadata["status"] = status.name

    priority = best_effort_get_field_from_issue(issue, "priority")
    if priority is not None:
        metadata["priority"] = priority.name

    issuetype = best_effort_get_field_from_issue(issue, "issuetype")
    if issuetype is not None:
        metadata["issue_type"] = issuetype.name

    updated_str = best_effort_get_field_from_issue(issue, "updated")
    doc_updated_at: datetime | None = None
    if updated_str:
        try:
            doc_updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
        except Exception:
            pass

    primary_owners = None
    reporter = best_effort_get_field_from_issue(issue, "reporter")
    if reporter is not None and (expert := best_effort_basic_expert_info(reporter)):
        primary_owners = [expert]

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {summary}",
        title=f"{issue.key} {summary}",
        doc_updated_at=doc_updated_at,
        primary_owners=primary_owners,
        metadata=metadata,
    )


class JiraServiceManagementConnector(CheckpointedConnector[JiraServiceManagementCheckpoint]):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = project_key
        self.batch_size = batch_size
        self._jira_client: JIRA | None = None

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
        )
        return None

    def _build_jql(self, start: SecondsSinceUnixEpoch | None) -> str:
        issue_types = ", ".join(_JSM_ISSUE_TYPES)
        base_jql = (
            f'project = "{self.project_key}" AND issuetype in ({issue_types})'
        )
        if start is not None and start > 0:
            start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )
            return f'{base_jql} AND updated >= "{start_str}"'
        return base_jql

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        jql = self._build_jql(start)
        current_start = checkpoint.start_at

        while True:
            try:
                issues = self.jira_client.search_issues(
                    jql,
                    startAt=current_start,
                    maxResults=self.batch_size,
                    fields="summary,description,comment,status,priority,issuetype,reporter,updated",
                )
            except Exception as e:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=f"jql:{jql}:page:{current_start}",
                    ),
                    failure_message=f"Failed to fetch JSM issues: {e}",
                    exception=e,
                )
                return JiraServiceManagementCheckpoint(
                    start_at=current_start, has_more=False
                )

            if not issues:
                return JiraServiceManagementCheckpoint(
                    start_at=current_start, has_more=False
                )

            for issue in issues:
                try:
                    doc = _process_jsm_issue(self.jira_base, issue)
                    if doc is not None:
                        yield doc
                except Exception as e:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=issue.key,
                            document_link=build_jira_url(self.jira_base, issue.key),
                        ),
                        failure_message=f"Failed to process JSM issue {issue.key}: {e}",
                        exception=e,
                    )

            fetched = len(issues)
            current_start += fetched

            if fetched < self.batch_size:
                return JiraServiceManagementCheckpoint(
                    start_at=current_start, has_more=False
                )

            # Yield an intermediate checkpoint after each page so indexing can resume
            yield JiraServiceManagementCheckpoint(
                start_at=current_start, has_more=True
            )

    def build_dummy_checkpoint(self) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraServiceManagementCheckpoint:
        return JiraServiceManagementCheckpoint.model_validate_json(checkpoint_json)
