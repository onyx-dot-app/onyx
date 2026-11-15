import re
from collections.abc import Generator
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    JIRA_CONNECTOR_MAX_TICKET_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraIssue,
    _issue_key,
    _FIELD_ASSIGNEE,
    _FIELD_CREATED,
    _FIELD_KEY,
    _FIELD_LABELS,
    _FIELD_PARENT,
    _FIELD_PRIORITY,
    _FIELD_PROJECT,
    _FIELD_PROJECT_NAME,
    _FIELD_REPORTER,
    _FIELD_RESOLUTION,
    _FIELD_STATUS,
    _FIELD_UPDATED,
    process_jira_issue,
)
from onyx.connectors.jira.utils import (
    best_effort_basic_expert_info,
    build_jira_url,
    get_issue_field,
    get_named_field,
    rich_text,
)
from onyx.connectors.models import (
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM-specific metadata keys
_FIELD_JSM_REQUEST_TYPE = "request_type"
_FIELD_JSM_PORTAL_STATUS = "portal_status"
_FIELD_JSM_ORGANIZATIONS = "organizations"
_FIELD_JSM_REQUEST_PARTICIPANTS = "request_participants"
_FIELD_JSM_SLA_BREACHED = "sla_breached"
_FIELD_JSM_SERVICE_DESK_ID = "service_desk_id"


def _extract_jsm_request_type(issue: JiraIssue) -> str | None:
    """Extract Customer Request Type from standard JSM custom fields."""
    fields = issue.get("fields") or {}
    for key, val in fields.items():
        if not val or not isinstance(val, dict):
            continue
        # Standard JSM requestType structure
        if "requestType" in val and isinstance(val["requestType"], dict):
            name = val["requestType"].get("name")
            if name:
                return str(name)
        if "_type" in val and "requestType" in str(val.get("_type", "")).lower():
            name = val.get("name")
            if name:
                return str(name)
        # Direct name attribute on a request type object
        if key in ("customfield_10010", "requestType", "customerRequestType"):
            name = val.get("name") or val.get("value")
            if name:
                return str(name)
    return None


def _extract_jsm_organizations(issue: JiraIssue) -> list[str]:
    """Extract Customer Organizations associated with the JSM ticket."""
    fields = issue.get("fields") or {}
    org_names: list[str] = []
    for key, val in fields.items():
        if not val:
            continue
        if "organizations" in key.lower() or key == "customfield_10002":
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and "name" in item:
                        org_names.append(str(item["name"]))
                    elif isinstance(item, str):
                        org_names.append(item)
    return org_names


def _extract_jsm_participants(issue: JiraIssue) -> list[str]:
    """Extract Request Participants (customers/stakeholders) from the JSM ticket."""
    fields = issue.get("fields") or {}
    participants: list[str] = []
    for key, val in fields.items():
        if not val:
            continue
        if "participants" in key.lower() or key == "customfield_10003":
            if isinstance(val, list):
                for p in val:
                    if isinstance(p, dict):
                        email = p.get("emailAddress") or p.get("displayName") or p.get("name")
                        if email:
                            participants.append(str(email))
                    elif isinstance(p, str):
                        participants.append(p)
    return participants


def _check_jsm_sla_breached(issue: JiraIssue) -> bool:
    """Check if any Service Level Agreement (SLA) timer has breached."""
    fields = issue.get("fields") or {}
    for key, val in fields.items():
        if not val or not isinstance(val, dict):
            continue
        if "sla" in key.lower() or "timeto" in key.lower():
            ongoing_cycle = val.get("ongoingCycle")
            if isinstance(ongoing_cycle, dict):
                if ongoing_cycle.get("breached") is True:
                    return True
            completed_cycles = val.get("completedCycles")
            if isinstance(completed_cycles, list):
                for cycle in completed_cycles:
                    if isinstance(cycle, dict) and cycle.get("breached") is True:
                        return True
    return False


def _get_jsm_comment_strs(
    issue: JiraIssue,
    comment_email_blacklist: tuple[str, ...] = (),
    customer_visible_only: bool = True,
) -> list[str]:
    """Extract comments from JSM ticket, with optional filtering for customer-visible comments."""
    comment_field: dict[str, Any] = get_issue_field(issue, "comment") or {}
    comment_strs: list[str] = []
    
    for comment in comment_field.get("comments", []):
        try:
            author: dict[str, Any] = comment.get("author") or {}
            author_email = author.get("emailAddress")
            if author_email and author_email in comment_email_blacklist:
                continue

            # In Jira Service Management, internal agent notes are marked as private
            if customer_visible_only:
                # 1. Check jsdPublic flag
                if comment.get("jsdPublic") is False:
                    continue
                # 2. Check properties for sd.public.comment
                properties = comment.get("properties") or []
                is_internal = False
                if isinstance(properties, list):
                    for prop in properties:
                        if isinstance(prop, dict) and prop.get("key") == "sd.public.comment":
                            internal_val = (prop.get("value") or {}).get("internal")
                            if internal_val is True:
                                is_internal = True
                                break
                if is_internal:
                    continue
                # 3. Check visibility object (role / group restrictions)
                visibility = comment.get("visibility")
                if isinstance(visibility, dict) and visibility.get("type") in ("role", "group"):
                    role_val = str(visibility.get("value", "")).lower()
                    if "agent" in role_val or "internal" in role_val or "developer" in role_val:
                        continue

            text_body = rich_text(comment.get("body"))
            if text_body:
                comment_strs.append(text_body)
        except Exception as e:
            logger.error("Failed to process JSM comment: %s", e)
            continue

    return comment_strs


def process_jsm_issue(
    jira_base_url: str,
    issue: JiraIssue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
    customer_visible_only: bool = True,
    service_desk_id: str | None = None,
) -> Document | None:
    """Transforms a Jira Service Management ticket into an Onyx Document with JSM metadata."""
    issue_key = _issue_key(issue)
    issue_labels: list[str] = get_issue_field(issue, _FIELD_LABELS) or []
    if labels_to_skip and any(label in issue_labels for label in labels_to_skip):
        logger.info("Skipping JSM issue %s due to label filter", issue_key)
        return None

    description: str = rich_text(get_issue_field(issue, "description"))
    comments = _get_jsm_comment_strs(
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
        customer_visible_only=customer_visible_only,
    )

    ticket_content = f"{description}\n" + "\n".join(
        [f"Comment: {c}" for c in comments if c]
    )

    if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        logger.info("Skipping JSM issue %s because it exceeds max size limit", issue_key)
        return None

    page_url = build_jira_url(jira_base_url, issue_key)
    metadata_dict: dict[str, Any] = {}
    people = set()

    creator: Any = get_issue_field(issue, _FIELD_REPORTER)
    if creator is not None and (expert_info := best_effort_basic_expert_info(creator)):
        people.add(expert_info)
        metadata_dict[_FIELD_REPORTER] = expert_info.get_semantic_name()
        if email := expert_info.get_email():
            metadata_dict["reporter_email"] = email

    assignee: Any = get_issue_field(issue, _FIELD_ASSIGNEE)
    if assignee is not None and (expert_info := best_effort_basic_expert_info(assignee)):
        people.add(expert_info)
        metadata_dict[_FIELD_ASSIGNEE] = expert_info.get_semantic_name()
        if email := expert_info.get_email():
            metadata_dict["assignee_email"] = email

    metadata_dict[_FIELD_KEY] = issue_key
    if priority := get_named_field(issue, _FIELD_PRIORITY):
        metadata_dict[_FIELD_PRIORITY] = priority
    if status := get_named_field(issue, _FIELD_STATUS):
        metadata_dict[_FIELD_STATUS] = status
        metadata_dict[_FIELD_JSM_PORTAL_STATUS] = status
    if resolution := get_named_field(issue, _FIELD_RESOLUTION):
        metadata_dict[_FIELD_RESOLUTION] = resolution
    if issue_labels:
        metadata_dict[_FIELD_LABELS] = issue_labels
    if created := get_issue_field(issue, _FIELD_CREATED):
        metadata_dict[_FIELD_CREATED] = created
    if updated := get_issue_field(issue, _FIELD_UPDATED):
        metadata_dict[_FIELD_UPDATED] = updated

    parent: Any = get_issue_field(issue, _FIELD_PARENT)
    if parent is not None and _FIELD_KEY in parent:
        metadata_dict[_FIELD_PARENT] = parent[_FIELD_KEY]

    project: Any = get_issue_field(issue, _FIELD_PROJECT)
    if project is not None:
        metadata_dict[_FIELD_PROJECT_NAME] = project.get("name", "")
        metadata_dict[_FIELD_PROJECT] = project.get(_FIELD_KEY, "")

    # JSM specific metadata extraction
    if req_type := _extract_jsm_request_type(issue):
        metadata_dict[_FIELD_JSM_REQUEST_TYPE] = req_type
    if orgs := _extract_jsm_organizations(issue):
        metadata_dict[_FIELD_JSM_ORGANIZATIONS] = orgs
    if participants := _extract_jsm_participants(issue):
        metadata_dict[_FIELD_JSM_REQUEST_PARTICIPANTS] = participants
    if _check_jsm_sla_breached(issue):
        metadata_dict[_FIELD_JSM_SLA_BREACHED] = "true"
    if service_desk_id:
        metadata_dict[_FIELD_JSM_SERVICE_DESK_ID] = str(service_desk_id)

    summary: Any = get_issue_field(issue, "summary") or ""
    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"JSM {issue_key}: {summary}",
        title=f"[{issue_key}] {summary}",
        doc_updated_at=time_str_to_utc(get_issue_field(issue, _FIELD_UPDATED)),
        doc_created_at=time_str_to_utc(get_issue_field(issue, _FIELD_CREATED)),
        primary_owners=list(people) or None,
        metadata=metadata_dict,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )


class JiraServiceManagementConnector(JiraConnector):
    """Jira Service Management (JSM) Connector.
    
    Subclasses JiraConnector to pull tickets, customer requests, comments,
    and metadata from Jira Service Management projects, assigning DocumentSource.JIRA_SERVICE_MANAGEMENT.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        customer_visible_only: bool = True,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self.service_desk_id = service_desk_id
        self.customer_visible_only = customer_visible_only

    @override
    def _issue_to_items(
        self,
        issue: JiraIssue,
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        project = get_issue_field(issue, _FIELD_PROJECT)
        project_key = project[_FIELD_KEY] if project else None
        project_name = project.get("name") if project else None

        if project_key:
            yield from self._yield_project_hierarchy_node(
                project_key, project_name, seen_hierarchy_node_ids
            )
            parent = get_issue_field(issue, _FIELD_PARENT)
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
            customer_visible_only=self.customer_visible_only,
            service_desk_id=self.service_desk_id,
        ):
            if include_permissions and project_key:
                document.external_access = self._get_project_permissions(
                    project_key,
                    add_prefix=True,
                )
            yield document
