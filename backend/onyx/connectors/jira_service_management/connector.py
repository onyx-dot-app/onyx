from collections.abc import Iterator
from datetime import datetime, timezone
import logging
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    BaseConnector,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import BasicExpertInfo, Document, Section
from onyx.connectors.jira_service_management.client import JiraServiceManagementAPI, JSMIssue
from onyx.connectors.jira_service_management.config import JSMConnectorConfig

logger = logging.getLogger(__name__)

class JSMConnector(BaseConnector, LoadConnector, PollConnector):
    def __init__(
        self,
        config: JSMConnectorConfig | None = None,
        project_key: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] | None = None,
        **kwargs: Any,
    ):
        super().__init__()
        if config:
            self.project_key = config.project_key
            self.batch_size = config.batch_size
            self.labels_to_skip = config.labels_to_skip
            self.base_url = config.jsm_base_url
            self.user_email = config.jsm_user_email
            self.api_token = config.jsm_api_token
        else:
            self.project_key = project_key
            self.batch_size = batch_size
            self.labels_to_skip = labels_to_skip or []
            self.base_url = kwargs.get("jsm_base_url", "")
            self.user_email = kwargs.get("jsm_user_email", "")
            self.api_token = kwargs.get("jsm_api_token", "")

        self.jsm_client = JiraServiceManagementAPI(
            base_url=self.base_url,
            user_email=self.user_email,
            api_token=self.api_token,
            labels_to_skip=self.labels_to_skip,
        )

    def _convert_issue_to_document(self, issue: JSMIssue) -> Document:
        sections = [
            Section(
                text=f"Summary: {issue.summary}\n\nDescription:\n{issue.description}",
                link=issue.url,
            )
        ]
        if issue.comments:
            sections.append(
                Section(
                    text="Comments:\n" + "\n---\n".join(issue.comments),
                    link=f"{issue.url}#comments",
                )
            )

        primary_owners = []
        if issue.assigned_to and issue.assigned_to.email:
            primary_owners.append(
                BasicExpertInfo(
                    display_name=issue.assigned_to.name,
                    email=issue.assigned_to.email,
                )
            )

        return Document(
            id=issue.url,
            sections=sections,
            source=DocumentSource.JIRA,
            semantic_identifier=f"[{issue.key}] {issue.summary}",
            metadata={
                "ticket_key": issue.key,
                "status": issue.status,
                "priority": issue.priority,
                "labels": issue.labels,
                "created_by": issue.created_by.name,
            },
            doc_updated_at=issue.last_modified_time,
            primary_owners=primary_owners,
        )

    def load_from_state(self) -> Iterator[list[Document]]:
        logger.info(f"Indexing all tickets in JSM project: {self.project_key}")
        for batch in self.jsm_client.get_issues(
            project_key=self.project_key,
            batch_size=self.batch_size,
        ):
            yield [self._convert_issue_to_document(issue) for issue in batch]

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[list[Document]]:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        logger.info(f"Polling JSM project {self.project_key} from {start_dt} to {end_dt}")
        for batch in self.jsm_client.get_issues(
            project_key=self.project_key,
            start_time=start_dt,
            end_time=end_dt,
            batch_size=self.batch_size,
        ):
            yield [self._convert_issue_to_document(issue) for issue in batch]
