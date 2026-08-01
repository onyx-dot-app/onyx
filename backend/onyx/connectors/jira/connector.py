from typing import List, Dict, Any, Generator, Iterable
import requests
import copy
from datetime import datetime, timezone

from jira import JIRA
from jira.exceptions import JIRAError

from onyx.connectors.interfaces import PollConnector, SlimConnector, SlimConnectorWithPermSync, CheckpointedConnectorWithPermSync, CheckpointOutput, ConnectorCheckpoint
from onyx.connectors.models import Document, TextSection, HierarchyNode, HierarchyNodeType
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_BATCH_SIZE
from onyx.utils.logger import setup_logger
from onyx.connectors.jira.utils import (
    JIRA_CONNECTOR_MAX_TICKET_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    _JIRA_FULL_PAGE_SIZE,
    _FIELD_REPORTER,
    _FIELD_ASSIGNEE,
    _FIELD_PRIORITY,
    _FIELD_STATUS,
    _FIELD_RESOLUTION,
    _FIELD_LABELS,
    _FIELD_CREATED,
    _FIELD_UPDATED,
    _FIELD_DUEDATE,
    _FIELD_ISSUETYPE,
    _FIELD_RESOLUTION_DATE,
    _FIELD_RESOLUTION_DATE_KEY,
    _FIELD_PARENT,
    _FIELD_PROJECT,
    _FIELD_PROJECT_NAME,
    _FIELD_REPORTER_EMAIL,
    _FIELD_ASSIGNEE_EMAIL,
    _FIELD_KEY,
    build_jira_url,
    build_jira_client,
    get_project_permissions,
    extract_text_from_adf,
    get_comment_strs,
    best_effort_get_field_from_issue,
    best_effort_basic_expert_info,
    time_str_to_utc,
    is_atlassian_date_error,
    make_checkpoint_callback,
    enhanced_search_ids,
    bulk_fetch_issues
)
from onyx.utils.general import chunked
from onyx.server.documents.models import SecondsSinceUnixEpoch
from onyx.errors import ConnectorMissingCredentialError

logger = setup_logger()

def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    all_issue_ids: list[list[str]] | None = None,
    checkpoint_callback: Any = None,
    nextPageToken: str | None = None,
    ids_done: bool = False,
    fields: str | None = None,
) -> Iterable[Issue]:
    """
    The way this works is we get all the issue ids and bulk fetch them in batches.
    However, for really large deployments we can't do these operations sequentially,
    as it might take several hours to fetch all the issue ids.

    So, each run of this function does at least one of:
     - fetch a batch of issue ids
     - bulk fetch a batch of issues

    If all_issue_ids is not None, we use it to bulk fetch issues.
    """
    if not ids_done:
        new_ids, pageToken = enhanced_search_ids(jira_client, jql, nextPageToken)
        if checkpoint_callback is not None:
            checkpoint_callback(chunked(new_ids, max_results), pageToken)

    if all_issue_ids:
        yield from bulk_fetch_issues(jira_client, all_issue_ids.pop(), fields)


def _perform_jql_search_v2(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
) -> Iterable[Any]:
    logger.debug(
        "Fetching Jira issues with JQL: %s, starting at %s, max results: %s",
        jql,
        start,
        max_results,
    )
    try:
        issues = jira_client.search_issues(
            jql_str=jql,
            startAt=start,
            maxResults=max_results,
            fields=fields,
        )
    except JIRAError as e:
        # _handle_jira_search_error(e, jql)
        raise

    for issue in issues:
        yield issue


def process_jira_issue(
    jira_base_url: str,
    issue: Any,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    if labels_to_skip:
        if any(label in issue.fields.labels for label in labels_to_skip):
            return None

    if isinstance(issue.fields.description, str):
        description = issue.fields.description
    else:
        description = extract_text_from_adf(issue.raw["fields"]["description"])

    comments = get_comment_strs(
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
    )
    ticket_content = f"{description}\n" + "\n".join(
        [f"Comment: {comment}" for comment in comments if comment]
    )

    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        return None

    page_url = build_jira_url(jira_base_url, issue.key)
    metadata_dict: dict[str, str | list[str]] = {}
    people = set()

    metadata_dict[_FIELD_KEY] = issue.key
    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        doc_created_at=time_str_to_utc(issue.fields.created),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )


class JiraConnectorCheckpoint(ConnectorCheckpoint):
    all_issue_ids: list[list[str]] = []
    ids_done: bool = False
    cursor: str | None = None
    offset: int | None = None
    seen_hierarchy_node_ids: list[str] = []


class JiraConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.jql_query = jql_query
        self.scoped_token = scoped_token
        self._jira_client: JIRA | None = None
        self._project_permissions_cache: dict[str, Any] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
            scoped_token=self.scoped_token,
        )
        return None

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        return CheckpointOutput(doc_batch=[], checkpoint=checkpoint)


# ==========================================
# SUA IMPLEMENTAÇÃO CUSTOMIZADA (JSM)
# ==========================================
class JiraServiceManagementConnector(PollConnector):
    """
    Sovereign implementation for Jira Service Management.
    Handles paginated ticket indexing and secure credential loading.
    """
    def __init__(self, **kwargs: Any):
        self.username: str | None = None
        self.api_token: str | None = None
        self.url: str | None = None
        self.project_key: str | None = None

    def load_credentials(self, db_credentials: Dict[str, Any]) -> None:
        """Injects credentials from Onyx database into the connector instance."""
        self.username = db_credentials.get("username")
        self.api_token = db_credentials.get("api_token")
        self.url = db_credentials.get("url", "").rstrip("/")
        self.project_key = db_credentials.get("project_key")
        
        if not all([self.username, self.api_token, self.url, self.project_key]):
            logger.error("Jira JSM: Missing required credentials in db_credentials.")
            raise ValueError("Jira JSM: missing required credentials in db_credentials")

    def poll(self) -> List[Document]:
        """Entry point for the Onyx indexing pipeline."""
        all_docs = []
        start_at = 0
        max_results = 50
        
        if not self.project_key:
            logger.error("Jira JSM: No project key provided.")
            return []

        logger.info(f"Starting JSM poll for project: {self.project_key}")
        
        while True:
            try:
                data = self._fetch_tickets(start_at, max_results)
                issues = data.get("issues", [])
                if not issues:
                    break
                
                for issue in issues:
                    doc = self._map_issue_to_document(issue)
                    all_docs.append(doc)
                
                start_at += max_results
                if start_at >= data.get("total", 0):
                    break
            except Exception as e:
                logger.error(f"Failed to fetch JSM tickets at offset {start_at}: {e}")
                break
                
        return all_docs

    def _fetch_tickets(self, start_at: int, max_results: int) -> Dict[str, Any]:
        """Raw API call to Jira REST API v2 search endpoint."""
        url = f"{self.url}/rest/api/2/search"
        params = {
            "jql": f"project = {self.project_key}",
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["summary", "description", "updated", "created"]
        }
        response = requests.get(
            url, 
            auth=(self.username, self.api_token), 
            params=params,
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def _map_issue_to_document(self, issue: Dict[str, Any]) -> Document:
        """Converts a Jira JSON issue into a standard Onyx Document."""
        key = issue.get("key")
        fields = issue.get("fields", {})
        page_url = f"{self.url}/browse/{key}"
        
        return Document(
            id=page_url,
            sections=[
                TextSection(
                    link=page_url, 
                    text=fields.get("description") or "No description provided."
                )
            ],
            source=DocumentSource.JIRA,
            semantic_identifier=f"{key}: {fields.get('summary')}",
            title=f"[{key}] {fields.get('summary')}",
            metadata={
                "project": self.project_key,
                "issue_key": key,
                "status": fields.get("status", {}).get("name") if isinstance(fields.get("status"), dict) else "Unknown"
            }
        )