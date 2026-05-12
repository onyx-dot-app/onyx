"""Jira Service Management connector.

Extends the Jira connector to handle JSM-specific fields:
- Request type (the service request category)
- SLA information (time to first response, time to resolution)
- Customer / participant info
"""

import copy
from typing import Any

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraConnectorCheckpoint,
    _FIELD_PARENT,
    _FIELD_PROJECT,
    _JIRA_FULL_PAGE_SIZE,
    _perform_jql_search,
    build_jira_url,
    make_checkpoint_callback,
    process_jira_issue,
)
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM-specific custom field IDs (standard defaults; vary per Jira instance)
_JSM_FIELD_REQUEST_TYPE = "customfield_10010"
_JSM_FIELD_SLA_RESPONSE = "customfield_10020"
_JSM_FIELD_SLA_RESOLUTION = "customfield_10030"

# Metadata keys for JSM fields
_JSM_META_REQUEST_TYPE = "request_type"
_JSM_META_SLA_RESPONSE = "sla_time_to_first_response"
_JSM_META_SLA_RESOLUTION = "sla_time_to_resolution"
_JSM_META_SLA_RESPONSE_BREACHED = "sla_time_to_first_response_breached"
_JSM_META_SLA_RESOLUTION_BREACHED = "sla_time_to_resolution_breached"


def _extract_jsm_request_type(issue: Issue) -> str | None:
    """Extract the JSM request type name from an issue.

    The request type is stored in customfield_10010 with a nested structure like:
    {"requestType": {"id": "1", "name": "IT Help", ...}}
    """
    try:
        field = best_effort_get_field_from_issue(issue, _JSM_FIELD_REQUEST_TYPE)
        if field is None:
            return None

        # Dict representation (raw JSON from API)
        if isinstance(field, dict):
            rt = field.get("requestType")
            if isinstance(rt, dict):
                return rt.get("name")
            return field.get("name")

        # Object representation (jira library)
        if hasattr(field, "requestType"):
            rt = field.requestType
            if hasattr(rt, "name"):
                return str(rt.name)
            if isinstance(rt, dict):
                return rt.get("name")

        if hasattr(field, "name"):
            return str(field.name)

    except Exception as e:
        logger.debug(f"Could not extract JSM request type: {e}")

    return None


def _extract_jsm_sla(sla_field: Any) -> tuple[str | None, bool | None]:
    """Extract SLA goal duration and breached status from a JSM SLA field.

    Returns (goal_duration_friendly, is_breached).
    """
    if sla_field is None:
        return None, None

    try:
        # Normalize to dict
        sla_dict: dict[str, Any]
        if isinstance(sla_field, dict):
            sla_dict = sla_field
        elif hasattr(sla_field, "raw"):
            sla_dict = sla_field.raw
        else:
            return None, None

        # Ongoing cycle takes precedence
        ongoing = sla_dict.get("ongoingCycle")
        if ongoing and isinstance(ongoing, dict):
            breached: bool | None = ongoing.get("breached")
            goal: Any = ongoing.get("goalDuration")
            friendly = goal.get("friendly") if isinstance(goal, dict) else None
            return friendly, breached

        # Fall back to last completed cycle
        completed = sla_dict.get("completedCycles")
        if completed and isinstance(completed, list) and len(completed) > 0:
            last = completed[-1]
            if isinstance(last, dict):
                breached = last.get("breached")
                goal = last.get("goalDuration")
                friendly = goal.get("friendly") if isinstance(goal, dict) else None
                return friendly, breached

    except Exception as e:
        logger.debug(f"Could not extract JSM SLA info: {e}")

    return None, None


def _enrich_document_with_jsm_fields(
    document: Document,
    issue: Issue,
) -> Document:
    """Add JSM-specific metadata to an already-processed Jira document."""
    # Change source to JIRA_SERVICE_MANAGEMENT
    document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    metadata = document.metadata

    # Request type
    request_type = _extract_jsm_request_type(issue)
    if request_type:
        metadata[_JSM_META_REQUEST_TYPE] = request_type

    # SLA: time to first response
    sla_response_field = best_effort_get_field_from_issue(
        issue, _JSM_FIELD_SLA_RESPONSE
    )
    sla_response_friendly, sla_response_breached = _extract_jsm_sla(sla_response_field)
    if sla_response_friendly is not None:
        metadata[_JSM_META_SLA_RESPONSE] = sla_response_friendly
    if sla_response_breached is not None:
        metadata[_JSM_META_SLA_RESPONSE_BREACHED] = str(sla_response_breached).lower()

    # SLA: time to resolution
    sla_resolution_field = best_effort_get_field_from_issue(
        issue, _JSM_FIELD_SLA_RESOLUTION
    )
    sla_resolution_friendly, sla_resolution_breached = _extract_jsm_sla(
        sla_resolution_field
    )
    if sla_resolution_friendly is not None:
        metadata[_JSM_META_SLA_RESOLUTION] = sla_resolution_friendly
    if sla_resolution_breached is not None:
        metadata[_JSM_META_SLA_RESOLUTION_BREACHED] = str(
            sla_resolution_breached
        ).lower()

    return document


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management (JSM).

    Uses the same Jira REST API and authentication as the regular Jira connector
    but extracts JSM-specific fields: request type and SLA information.

    The `project_key` should be the key of a JSM service desk project.
    """

    @override
    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        starting_offset = checkpoint.offset or 0
        current_offset = starting_offset
        new_checkpoint = copy.deepcopy(checkpoint)

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
                project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
                project_key = project.key if project else None
                project_name = project.name if project else None

                # Yield hierarchy nodes before document (parent-before-child)
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

                parent_hierarchy_raw_node_id = (
                    self._get_parent_hierarchy_raw_node_id(issue, project_key)
                    if project_key
                    else None
                )

                if document := process_jira_issue(
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                    parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                ):
                    document = _enrich_document_with_jsm_fields(document, issue)

                    if include_permissions and project_key:
                        document.external_access = self._get_project_permissions(
                            project_key,
                            add_prefix=True,
                        )
                    yield document

            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=issue_key,
                        document_link=build_jira_url(self.jira_base, issue_key),
                    ),
                    failure_message=f"Failed to process JSM issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        new_checkpoint.seen_hierarchy_node_ids = list(seen_hierarchy_node_ids)
        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JIRA_FULL_PAGE_SIZE
        )

        return new_checkpoint


if __name__ == "__main__":
    import os
    import time
    from tests.daily.connectors.utils import load_all_from_connector

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JSM_PROJECT_KEY"),
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    result = load_all_from_connector(connector, start=0.0, end=time.time())
    for doc in result.documents:
        print(doc.id, doc.metadata)
