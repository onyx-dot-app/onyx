from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document, ConnectorFailure, DocumentFailure, TextSection
from onyx.connectors.jira.utils import build_jira_url, extract_text_from_adf, get_comment_strs, best_effort_get_field_from_issue, best_effort_basic_expert_info
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.utils.logger import setup_logger
from onyx.connectors.jira.connector import _perform_jql_search, _JIRA_FULL_PAGE_SIZE, _FIELD_PROJECT, _FIELD_PARENT, _FIELD_REPORTER, _FIELD_ASSIGNEE, _FIELD_PRIORITY, _FIELD_STATUS, _FIELD_RESOLUTION, _FIELD_LABELS, _FIELD_KEY, _FIELD_CREATED, _FIELD_DUEDATE, _FIELD_ISSUETYPE, _FIELD_ASSIGNEE_EMAIL, _FIELD_REPORTER_EMAIL, _FIELD_UPDATED, _FIELD_RESOLUTION_DATE, _FIELD_RESOLUTION_DATE_KEY, make_checkpoint_callback
from typing import Any
import copy

logger = setup_logger()

def process_jsm_issue(
    jira_base_url: str,
    issue: Any,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    if labels_to_skip:
        if any(label in issue.fields.labels for label in labels_to_skip):
            logger.info(
                "Skipping %s because it has a label to skip. Found labels: %s. Labels to skip: %s.",
                issue.key,
                issue.fields.labels,
                labels_to_skip,
            )
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
        logger.info(
            "Skipping %s because it exceeds the maximum size of %s bytes.",
            issue.key,
            JIRA_CONNECTOR_MAX_TICKET_SIZE,
        )
        return None

    page_url = build_jira_url(jira_base_url, issue.key)

    metadata_dict: dict[str, str | list[str]] = {}
    people = set()

    creator = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
    if creator is not None and (
        basic_expert_info := best_effort_basic_expert_info(creator)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_REPORTER] = basic_expert_info.get_semantic_name()
        if (
            email := basic_expert_info.get_email()
        ):
            metadata_dict[_FIELD_REPORTER_EMAIL] = email

    assignee = best_effort_get_field_from_issue(issue, _FIELD_ASSIGNEE)
    if assignee is not None and (
        basic_expert_info := best_effort_basic_expert_info(assignee)
    ):
        people.add(basic_expert_info)
        metadata_dict[_FIELD_ASSIGNEE] = basic_expert_info.get_semantic_name()
        if (
            email := basic_expert_info.get_email()
        ):
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
        metadata_dict["project_name"] = project.name
        metadata_dict[_FIELD_PROJECT] = project.key
    else:
        logger.error("Project should exist but does not for %s", issue.key)

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

class JiraServiceManagementConnectorCheckpoint(JiraConnectorCheckpoint):
    pass

class JiraServiceManagementConnector(JiraConnector):
    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _load_from_checkpoint(
        self, jql: str, checkpoint: JiraServiceManagementConnectorCheckpoint, include_permissions: bool
    ) -> Any:
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

                if document := process_jsm_issue(
                    jira_base_url=self.jira_base,
                    issue=issue,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                    parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
                ):
                    if include_permissions:
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
                    failure_message=f"Failed to process Jira Service Management issue: {str(e)}",
                    exception=e,
                )

            current_offset += 1

        new_checkpoint.seen_hierarchy_node_ids = list(seen_hierarchy_node_ids)

        self.update_checkpoint_for_next_run(
            new_checkpoint, current_offset, starting_offset, _JIRA_FULL_PAGE_SIZE
        )

        return new_checkpoint
