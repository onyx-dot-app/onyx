import os
import copy
import time
from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypedDict

from jira import JIRA
from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import CheckpointConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.onyx_jira.utils import best_effort_basic_expert_info
from onyx.connectors.onyx_jira.utils import best_effort_get_field_from_issue
from onyx.connectors.onyx_jira.utils import build_jira_client
from onyx.connectors.onyx_jira.utils import build_jira_url
from onyx.connectors.onyx_jira.utils import extract_text_from_adf
from onyx.connectors.onyx_jira.utils import get_comment_strs
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()

JIRA_API_VERSION = os.environ.get("JIRA_API_VERSION") or "2"
_JIRA_SLIM_PAGE_SIZE = 500
_JIRA_FULL_PAGE_SIZE = 50


def _perform_jql_search(
    jira_client: JIRA,
    jql: str,
    start: int,
    max_results: int,
    fields: str | None = None,
) -> Iterable[Issue]:
    logger.debug(
        f"Fetching Jira issues with JQL: {jql}, "
        f"starting at {start}, max results: {max_results}"
    )
    issues = jira_client.search_issues(
        jql_str=jql,
        startAt=start,
        maxResults=max_results,
        fields=fields,
    )

    for issue in issues:
        if isinstance(issue, Issue):
            yield issue
        else:
            raise RuntimeError(f"Found Jira object not of type Issue: {issue}")


def process_jira_issue(
    jira_client: JIRA,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> Document | None:
    if labels_to_skip:
        if any(label in issue.fields.labels for label in labels_to_skip):
            logger.info(
                f"Skipping {issue.key} because it has a label to skip. Found "
                f"labels: {issue.fields.labels}. Labels to skip: {labels_to_skip}."
            )
            return None

    description = (
        issue.fields.description
        if JIRA_API_VERSION == "2"
        else extract_text_from_adf(issue.raw["fields"]["description"])
    )
    comments = get_comment_strs(
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
    )
    ticket_content = f"{description}\n" + "\n".join(
        [f"Comment: {comment}" for comment in comments if comment]
    )

    # Check ticket size
    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        logger.info(
            f"Skipping {issue.key} because it exceeds the maximum size of "
            f"{JIRA_CONNECTOR_MAX_TICKET_SIZE} bytes."
        )
        return None

    page_url = build_jira_url(jira_client, issue.key)

    people = set()
    try:
        creator = best_effort_get_field_from_issue(issue, "creator")
        if basic_expert_info := best_effort_basic_expert_info(creator):
            people.add(basic_expert_info)
    except Exception:
        # Author should exist but if not, doesn't matter
        pass

    try:
        assignee = best_effort_get_field_from_issue(issue, "assignee")
        if basic_expert_info := best_effort_basic_expert_info(assignee):
            people.add(basic_expert_info)
    except Exception:
        # Author should exist but if not, doesn't matter
        pass

    metadata_dict = {}
    if priority := best_effort_get_field_from_issue(issue, "priority"):
        metadata_dict["priority"] = priority.name
    if status := best_effort_get_field_from_issue(issue, "status"):
        metadata_dict["status"] = status.name
    if resolution := best_effort_get_field_from_issue(issue, "resolution"):
        metadata_dict["resolution"] = resolution.name
    if labels := best_effort_get_field_from_issue(issue, "labels"):
        metadata_dict["labels"] = labels

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
    )


class JiraConnectorCheckpoint(ConnectorCheckpoint):
    offset: int | None = None


class JiraConnector(CheckpointConnector[JiraConnectorCheckpoint], SlimConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base = jira_base_url.rstrip("/")  # Remove trailing slash if present
        self.jira_project = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)

        self._jira_client: JIRA | None = None

    @property
    def comment_email_blacklist(self) -> tuple:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    @property
    def jira_client(self) -> JIRA:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")
        return self._jira_client

    @property
    def quoted_jira_project(self) -> str:
        # Quote the project name to handle reserved words
        if not self.jira_project:
            return ""
        return f'"{self.jira_project}"'

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
        )
        return None

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Get the JQL query based on whether a specific project is set and time range"""
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

        if self.jira_project:
            base_jql = f"project = {self.quoted_jira_project}"
            return f"{base_jql} AND {time_jql}"

        return time_jql

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)

        # Get the current offset from checkpoint or start at 0
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JIRA_FULL_PAGE_SIZE,
        ):
            issue_key = issue.key
            try:
                if document := process_jira_issue(
                    jira_client=self.jira_client,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                ):
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_client, issue_key),
                    ),
                    failure_message=f"Failed to process Jira issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        # Update checkpoint
        checkpoint = JiraConnectorCheckpoint(
            offset=current_offset,
            # if we didn't retrieve a full batch, we're done
            has_more=current_offset - starting_offset == _JIRA_FULL_PAGE_SIZE,
        )
        return checkpoint

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        jql = self._get_jql_query(start or 0, end or float("inf"))

        slim_doc_batch = []
        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=0,
            max_results=_JIRA_SLIM_PAGE_SIZE,
            fields="key",
        ):
            issue_key = best_effort_get_field_from_issue(issue, "key")
            id = build_jira_url(self.jira_client, issue_key)
            slim_doc_batch.append(
                SlimDocument(
                    id=id,
                    perm_sync_data=None,
                )
            )
            if len(slim_doc_batch) >= _JIRA_SLIM_PAGE_SIZE:
                yield slim_doc_batch
                slim_doc_batch = []

        yield slim_doc_batch
    
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput:
        """Load Jira issues with time-based chunking for scaling to millions of tickets."""
        if self.jira_client is None:
            raise ConnectorMissingCredentialError("Jira")
        
        # Initialize or get existing checkpoint content
        checkpoint_content = cast(
            JiraCheckpointContent,
            (
                copy.deepcopy(checkpoint.checkpoint_content)
                or {
                    "project_keys": None,
                    "current_project_index": 0,
                    "time_chunks": None,
                    "current_time_chunk_index": 0,
                    "current_offset": 0,
                    "seen_issue_keys": [],
                    "failed_issue_keys": {},
                    "overall_last_indexed_timestamp": 0,
                }
            ),
        )
        
        # First run - initialize projects and time chunks
        if checkpoint_content["project_keys"] is None:
            # Initialize projects
            if not self.jira_project:
                try:
                    accessible_projects = self.jira_client.projects()
                    checkpoint_content["project_keys"] = [p.key for p in accessible_projects]
                    logger.info(f"Found {len(checkpoint_content['project_keys'])} Jira projects to index")
                except Exception as e:
                    logger.error(f"Error fetching projects: {e}")
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(
                            entity_id="all_projects",
                            missed_time_range=(
                                datetime.fromtimestamp(start, tz=timezone.utc),
                                datetime.fromtimestamp(end, tz=timezone.utc),
                            ),
                        ),
                        failure_message=f"Failed to fetch Jira projects: {str(e)}",
                        exception=e,
                    )
                    # Return current checkpoint to retry
                    return checkpoint
            else:
                checkpoint_content["project_keys"] = [self.jira_project]
            
            # Initialize time chunks
            # First, get the earliest project creation date
            earliest_time = time.time() - (5 * 365 * 24 * 60 * 60)  # Default to 5 years ago
            try:
                # Try to find earliest created issue
                for project_key in checkpoint_content["project_keys"][:5]:  # Limit to first 5 projects for efficiency
                    jql = f'project = "{project_key}" ORDER BY created ASC'
                    issues = self.jira_client.search_issues(jql_str=jql, maxResults=1)
                    if issues and len(issues) > 0:
                        issue_created = time_str_to_utc(issues[0].fields.created).timestamp()
                        earliest_time = min(earliest_time, issue_created)
            except Exception as e:
                logger.warning(f"Error determining earliest issue date, using default 5 years ago: {e}")
            
            # Create time chunks - default to 3-month chunks
            now = time.time()
            chunk_size = _DEFAULT_TIME_CHUNK_SIZE  # 3 months in seconds
            chunks = []
            
            current_start = earliest_time
            while current_start < now:
                current_end = min(current_start + chunk_size, now)
                chunks.append((int(current_start), int(current_end)))
                current_start = current_end
            
            # Reverse the chunks to process newest first
            chunks.reverse()
            
            checkpoint_content["time_chunks"] = chunks
            logger.info(f"Created {len(chunks)} time chunks for Jira indexing, spanning from "
                      f"{datetime.fromtimestamp(earliest_time)} to {datetime.fromtimestamp(now)}")
        
        # Check if we've processed all projects or time chunks
        if (not checkpoint_content["project_keys"] or 
            checkpoint_content["current_project_index"] >= len(checkpoint_content["project_keys"]) or
            not checkpoint_content["time_chunks"] or 
            checkpoint_content["current_time_chunk_index"] >= len(checkpoint_content["time_chunks"])):
            return ConnectorCheckpoint(
                checkpoint_content=checkpoint_content,
                has_more=False
            )
        
        # Get current processing state
        current_project_idx = checkpoint_content["current_project_index"]
        current_project = checkpoint_content["project_keys"][current_project_idx]
        
        current_time_chunk_idx = checkpoint_content["current_time_chunk_index"]
        current_time_chunk = checkpoint_content["time_chunks"][current_time_chunk_idx]
        time_chunk_start, time_chunk_end = current_time_chunk
        
        current_offset = checkpoint_content["current_offset"]
        
        # Build JQL query with time constraints
        start_date_str = datetime.fromtimestamp(time_chunk_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        end_date_str = datetime.fromtimestamp(time_chunk_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        
        jql = f'project = "{current_project}" AND created >= "{start_date_str}" AND created <= "{end_date_str}"'
        
        try:
            logger.info(f"Fetching Jira issues for project {current_project}, time window "
                      f"{start_date_str} to {end_date_str}, offset {current_offset}")
            
            # Fetch issues with pagination
            issues = self.jira_client.search_issues(
                jql_str=jql,
                startAt=current_offset,
                maxResults=_JIRA_FULL_PAGE_SIZE,
            )
            
            # Process issues
            for issue in issues:
                issue_key = issue.key
                
                # Skip already processed issues
                if issue_key in checkpoint_content["seen_issue_keys"]:
                    continue
                    
                try:
                    # Process issue
                    document = None
                    for doc in fetch_jira_issues_batch(
                        jira_client=self.jira_client,
                        jql=f"key = {issue_key}",
                        batch_size=1,
                        comment_email_blacklist=self.comment_email_blacklist,
                        labels_to_skip=self.labels_to_skip,
                    ):
                        document = doc
                        break
                    
                    if document:
                        # Add to processed set
                        checkpoint_content["seen_issue_keys"].append(issue_key)
                        # Yield the document
                        yield document
                    
                except Exception as e:
                    # Track failure for retry in future runs
                    checkpoint_content["failed_issue_keys"][issue_key] = str(e)
                    logger.error(f"Error processing Jira issue {issue_key}: {e}")
                    
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(
                            entity_id=issue_key,
                            missed_time_range=(
                                datetime.fromtimestamp(time_chunk_start, tz=timezone.utc),
                                datetime.fromtimestamp(time_chunk_end, tz=timezone.utc),
                            ),
                        ),
                        failure_message=str(e),
                        exception=e,
                    )
            
            # Update checkpoint based on pagination results
            if len(issues) < _JIRA_FULL_PAGE_SIZE:
                # No more issues in this project+time chunk
                if current_project_idx < len(checkpoint_content["project_keys"]) - 1:
                    # Move to next project, same time chunk
                    checkpoint_content["current_project_index"] += 1
                    checkpoint_content["current_offset"] = 0
                else:
                    # Move to next time chunk, reset to first project
                    checkpoint_content["current_time_chunk_index"] += 1
                    checkpoint_content["current_project_index"] = 0
                    checkpoint_content["current_offset"] = 0
            else:
                # Update offset for next batch in same project+time chunk
                checkpoint_content["current_offset"] += len(issues)
            
            # Update overall last indexed timestamp if we're at the most recent time chunk
            if (checkpoint_content["current_time_chunk_index"] == 0 and
                checkpoint_content["current_project_index"] >= len(checkpoint_content["project_keys"]) - 1):
                checkpoint_content["overall_last_indexed_timestamp"] = int(time.time())
            
            # Return updated checkpoint
            has_more = (checkpoint_content["current_project_index"] < len(checkpoint_content["project_keys"]) or
                      checkpoint_content["current_time_chunk_index"] < len(checkpoint_content["time_chunks"]))
            
            return ConnectorCheckpoint(
                checkpoint_content=checkpoint_content,
                has_more=has_more
            )
            
        except Exception as e:
            # Handle general errors
            logger.exception(f"Error processing Jira project+time: {current_project}, {start_date_str}-{end_date_str}")
            yield ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=current_project,
                    missed_time_range=(
                        datetime.fromtimestamp(time_chunk_start, tz=timezone.utc),
                        datetime.fromtimestamp(time_chunk_end, tz=timezone.utc),
                    ),
                ),
                failure_message=str(e),
                exception=e,
            )
            return checkpoint

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        # If a specific project is set, validate it exists
        if self.jira_project:
            try:
                self.jira_client.project(self.jira_project)
            except Exception as e:
                status_code = getattr(e, "status_code", None)

                if status_code == 401:
                    raise CredentialExpiredError(
                        "Jira credential appears to be expired or invalid (HTTP 401)."
                    )
                elif status_code == 403:
                    raise InsufficientPermissionsError(
                        "Your Jira token does not have sufficient permissions for this project (HTTP 403)."
                    )
                elif status_code == 404:
                    raise ConnectorValidationError(
                        f"Jira project not found with key: {self.jira_project}"
                    )
                elif status_code == 429:
                    raise ConnectorValidationError(
                        "Validation failed due to Jira rate-limits being exceeded. Please try again later."
                    )

                raise RuntimeError(f"Unexpected Jira error during validation: {e}")
        else:
            # If no project specified, validate we can access the Jira API
            try:
                # Try to list projects to validate access
                self.jira_client.projects()
            except Exception as e:
                status_code = getattr(e, "status_code", None)
                if status_code == 401:
                    raise CredentialExpiredError(
                        "Jira credential appears to be expired or invalid (HTTP 401)."
                    )
                elif status_code == 403:
                    raise InsufficientPermissionsError(
                        "Your Jira token does not have sufficient permissions to list projects (HTTP 403)."
                    )
                elif status_code == 429:
                    raise ConnectorValidationError(
                        "Validation failed due to Jira rate-limits being exceeded. Please try again later."
                    )

                raise RuntimeError(f"Unexpected Jira error during validation: {e}")

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(
            has_more=True,
        )


if __name__ == "__main__":
    import os

    jira_base_url = os.environ.get("JIRA_BASE_URL", "")
    jira_project_key = os.environ.get("JIRA_PROJECT_KEY")
    jira_api_token = os.environ.get("JIRA_API_TOKEN", "")
    
    print(f"Connecting to Jira at {jira_base_url}")
    print(f"Project key: {jira_project_key or 'Not specified'}")
    
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key=jira_project_key,
        comment_email_blacklist=[],
    )

    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    document_batches = connector.load_from_checkpoint(
        0, float("inf"), JiraConnectorCheckpoint(has_more=True)
    )
    print(next(document_batches))
