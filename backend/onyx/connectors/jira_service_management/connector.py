import copy
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    is_atlassian_date_error,
)
from onyx.connectors.jira.connector import _FIELD_PROJECT
from onyx.connectors.jira.connector import _FIELD_PROJECT_NAME
from onyx.connectors.jira.connector import _FIELD_REPORTER
from onyx.connectors.jira.connector import _FIELD_REPORTER_EMAIL
from onyx.connectors.jira.connector import _FIELD_ASSIGNEE
from onyx.connectors.jira.connector import _FIELD_ASSIGNEE_EMAIL
from onyx.connectors.jira.connector import _FIELD_KEY
from onyx.connectors.jira.connector import _FIELD_PRIORITY
from onyx.connectors.jira.connector import _FIELD_STATUS
from onyx.connectors.jira.connector import _FIELD_RESOLUTION
from onyx.connectors.jira.connector import _FIELD_LABELS
from onyx.connectors.jira.connector import _FIELD_CREATED
from onyx.connectors.jira.connector import _FIELD_UPDATED
from onyx.connectors.jira.connector import _FIELD_DUEDATE
from onyx.connectors.jira.connector import _FIELD_ISSUETYPE
from onyx.connectors.jira.connector import _FIELD_PARENT
from onyx.connectors.jira.connector import _FIELD_RESOLUTION_DATE
from onyx.connectors.jira.connector import _FIELD_RESOLUTION_DATE_KEY
from onyx.connectors.jira.connector import _JIRA_FULL_PAGE_SIZE
from onyx.connectors.jira.connector import _perform_jql_search
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.connector import make_checkpoint_callback
from onyx.connectors.jira.utils import best_effort_basic_expert_info
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.connectors.jira.utils import get_comment_strs
from onyx.connectors.jira.utils import time_str_to_utc
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

ONE_HOUR = 3600
_FIELD_CUSTOMER_REQUEST_TYPE = "customfield_10010"  # This is the standard field name for Request Type in JSM


def process_jsm_issue(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    # Most of the logic is identical to Jira issues, but we want the JSM source
    doc = process_jira_issue_as_jsm(
        jira_base_url=jira_base_url,
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
        labels_to_skip=labels_to_skip,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    if doc:
        doc.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

        # Add JSM-specific fields if available
        # Customer Request Type
        request_type = best_effort_get_field_from_issue(issue, _FIELD_CUSTOMER_REQUEST_TYPE)
        if request_type:
            # Request Type is usually an object with a 'requestType' name or similar
            if isinstance(request_type, dict):
                inner_request_type = request_type.get("requestType")
                if isinstance(inner_request_type, dict):
                    name = inner_request_type.get("name")
                    doc.metadata["request_type"] = name or str(request_type)
                else:
                    doc.metadata["request_type"] = str(request_type)
            else:
                doc.metadata["request_type"] = str(request_type)
    return doc


def process_jira_issue_as_jsm(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    # Copy of process_jira_issue logic but we can't easily import it 
    # and change the source without modifying it.
    # Re-implementing a simplified version or just calling it and overriding.
    # But process_jira_issue is not easily overridable for source.
    
    # We'll just re-implement the core logic to ensure the source is correct from the start.
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

    page_url = build_jira_url(jira_base_url, issue.key)

    metadata_dict: dict[str, str | list[str]] = {}
    people = set()

    creator = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
    if creator is not None and (
        basic_expert_info := best_effort_basic_expert_info(creator)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_REPORTER] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_REPORTER_EMAIL] = email

    assignee = best_effort_get_field_from_issue(issue, _FIELD_ASSIGNEE)
    if assignee is not None and (
        basic_expert_info := best_effort_basic_expert_info(assignee)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_ASSIGNEE] = basic_expert_info.get_semantic_name()
        if email := basic_expert_info.get_email():
            metadata_dict[_FIELD_ASSIGNEE_EMAIL] = email

    metadata_dict[_FIELD_KEY] = issue.key
    if priority := best_effort_get_field_from_issue(issue, _FIELD_PRIORITY):
        metadata_dict[_FIELD_PRIORITY] = priority.name
    if status := best_effort_get_field_from_issue(issue, _FIELD_STATUS):
        metadata_dict[_FIELD_STATUS] = status.name
    if resolution := best_effort_get_field_from_issue(issue, _FIELD_RESOLUTION):
        metadata_dict[_FIELD_RESOLUTION] = resolution.name
    if labels := best_effort_get_field_from_issue(issue, _FIELD_LABELS):
        metadata_dict[_FIELD_LABELS] = labels
    if created := best_effort_get_field_from_issue(issue, _FIELD_CREATED):
        metadata_dict[_FIELD_CREATED] = created
    if updated := best_effort_get_field_from_issue(issue, _FIELD_UPDATED):
        metadata_dict[_FIELD_UPDATED] = updated
    if duedate := best_effort_get_field_from_issue(issue, _FIELD_DUEDATE):
        metadata_dict[_FIELD_DUEDATE] = duedate
    if issuetype := best_effort_get_field_from_issue(issue, _FIELD_ISSUETYPE):
        metadata_dict[_FIELD_ISSUETYPE] = issuetype.name
    if resolutiondate := best_effort_get_field_from_issue(
        issue, _FIELD_RESOLUTION_DATE
    ):
        metadata_dict[_FIELD_RESOLUTION_DATE_KEY] = resolutiondate

    parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
    if parent is not None:
        metadata_dict[_FIELD_PARENT] = parent.key

    project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
    if project is not None:
        metadata_dict[_FIELD_PROJECT_NAME] = project.name
        metadata_dict[_FIELD_PROJECT] = project.key

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue.key}: {issue.fields.summary}",
        title=f"{issue.key} {issue.fields.summary}",
        doc_updated_at=time_str_to_utc(issue.fields.updated),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )


class JiraServiceManagementConnector(JiraConnector):
    """
    Jira Service Management connector.
    Mostly identical to Jira but uses a different DocumentSource.
    """

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)
        try:
            return self._load_from_jsm_checkpoint(
                jql, checkpoint, include_permissions=False
            )
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return self._load_from_jsm_checkpoint(
                    jql, checkpoint, include_permissions=False
                )
            raise e

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        jql = self._get_jql_query(start, end)
        try:
            return self._load_from_jsm_checkpoint(
                jql, checkpoint, include_permissions=True
            )
        except Exception as e:
            if is_atlassian_date_error(e):
                jql = self._get_jql_query(start - ONE_HOUR, end)
                return self._load_from_jsm_checkpoint(
                    jql, checkpoint, include_permissions=True
                )
            raise e

    def _load_from_jsm_checkpoint(
        self, jql: str, checkpoint: JiraConnectorCheckpoint, include_permissions: bool
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        # Get the current offset from checkpoint or start at 0
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)

        # Convert checkpoint list to set for efficient lookups
        seen_hierarchy_node_ids = set(new_checkpoint.seen_hierarchy_node_ids)

        checkpoint_callback = make_checkpoint_callback(new_checkpoint)

        for issue in _perform_jql_search(
            jira_client=self.jira_client,
            jql=jql,
            start=current_offset,
            max_results=_JIRA_FULL_PAGE_SIZE,
            all_issue_ids=new_checkpoint.all_issue_ids,
            checkpoint_callback=checkpoint_callback,
            nextPageToken=new_checkpoint.cursor,
            ids_done=new_checkpoint.ids_done,
        ):
            issue_key = issue.key
            try:
                # Get project info for hierarchy
                project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
                project_key = project.key if project else None
                project_name = project.name if project else None

                # Yield hierarchy nodes BEFORE the document (parent-before-child)
                if project_key:
                    yield from self._yield_project_hierarchy_node(
                        project_key, project_name, seen_hierarchy_node_ids
                    )

                    parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
                    if parent:
                        yield from self._yield_parent_hierarchy_node_if_epic(
                            parent, project_key, seen_hierarchy_node_ids
                        )

                    if self._is_epic(issue):
                        yield from self._yield_epic_hierarchy_node(
                            issue, project_key, seen_hierarchy_node_ids
                        )

                # Determine parent hierarchy node ID for the document
                parent_hierarchy_raw_node_id = (
                    self._get_parent_hierarchy_raw_node_id(issue, project_key)
                    if project_key
                    else None
                )

                if document := process_jsm_issue(
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                    parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                ):
                    # Add permission information to the document if requested
                    if include_permissions:
                        document.external_access = self._get_project_permissions(
                            project_key,
                            add_prefix=True,  # Indexing path - prefix here
                        )
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=f"Failed to process JSM request: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        # Update checkpoint with seen hierarchy nodes
        new_checkpoint.seen_hierarchy_node_ids = list(seen_hierarchy_node_ids)

        # Update checkpoint
        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JIRA_FULL_PAGE_SIZE
        )

        return new_checkpoint
