import copy
import json
import os
from collections.abc import Callable, Generator, Iterable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from jira import JIRA
from jira.exceptions import JIRAError
from jira.resources import Issue
from more_itertools import chunked
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError, CredentialExpiredError, InsufficientPermissionsError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync, CheckpointOutput, SecondsSinceUnixEpoch, SlimConnectorWithPermSync
from onyx.connectors.jira_service_management.access import get_project_permissions
from onyx.connectors.jira_service_management.utils import best_effort_basic_expert_info, best_effort_get_field_from_issue, build_jira_client, build_jira_url, extract_text_from_adf, get_comment_strs
from onyx.connectors.models import ConnectorCheckpoint, ConnectorFailure, ConnectorMissingCredentialError, Document, DocumentFailure, HierarchyNode, SlimDocument, TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JIRA_FULL_PAGE_SIZE = 50

def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
) -> Iterable[Issue]:
    try:
        return jira_client.search_issues(
            jql_str=jql,
            startAt=start,
            maxResults=max_results,
            fields="*all",
        )
    except Exception as e:
        if hasattr(e, "status_code") and e.status_code == 401:
            raise CredentialExpiredError("Token inválido")
        raise e

def process_jira_issue(jira_base_url: str, issue: Issue) -> Document | None:
    raw_desc = getattr(issue.fields, "description", "")
    description = raw_desc if isinstance(raw_desc, str) else extract_text_from_adf(raw_desc)
    comments = get_comment_strs(issue)
    content = f"{description}\n" + "\n".join([f"Comment: {c}" for c in comments if c])
    page_url = build_jira_url(jira_base_url, issue.key)
    
    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        metadata={
            "key": issue.key,
            "status": getattr(issue.fields.status, "name", "N/A"),
            "project": issue.fields.project.key
        }
    )

class JiraServiceManagementConnectorCheckpoint(ConnectorCheckpoint):
    offset: int = 0

class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraServiceManagementConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(self, jira_base_url: str, **kwargs: Any) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self._jira_client: JIRA | None = None

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_client

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._jira_client = build_jira_client(credentials, self.jira_base)

    @override
    def load_from_checkpoint(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch, checkpoint: JiraServiceManagementConnectorCheckpoint
    ) -> Generator[Document | list[HierarchyNode] | JiraServiceManagementConnectorCheckpoint, None, None]:
        """Llama internamente a la versión con permisos."""
        yield from self.load_from_checkpoint_with_perm_sync(start, end, checkpoint)

    @override
    def load_from_checkpoint_with_perm_sync(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch, checkpoint: JiraServiceManagementConnectorCheckpoint
    ) -> Generator[Document | list[HierarchyNode] | JiraServiceManagementConnectorCheckpoint, None, None]:
        start_date = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        jql = f"updated >= '{start_date}'"
        
        current_offset = checkpoint.offset
        issues = _perform_jql_search(self.jira_client, jql, current_offset, _JIRA_FULL_PAGE_SIZE)
        
        found_any = False
        for issue in issues:
            found_any = True
            doc = process_jira_issue(self.jira_base, issue)
            if doc:
                yield doc
            current_offset += 1

        checkpoint.offset = current_offset
        checkpoint.has_more = found_any and len(issues) >= _JIRA_FULL_PAGE_SIZE
        yield checkpoint

    @override
    def retrieve_all_slim_docs_perm_sync(self) -> Generator[list[SlimDocument], None, None]:
        # Implementación mínima para cumplir el contrato
        yield []

    def build_dummy_checkpoint(self) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint(has_more=True)
    
    def validate_connector_settings(self) -> None:
        self.jira_client.projects()

    def validate_checkpoint_json(self, json_str: str) -> JiraServiceManagementConnectorCheckpoint:
        return JiraServiceManagementConnectorCheckpoint.model_validate_json(json_str)