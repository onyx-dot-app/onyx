import logging
from typing import Any

from jira.resources import Issue

from onyx.connectors.jira.utils import (
    best_effort_get_field_from_issue,
    extract_text_from_adf,
)

logger = logging.getLogger(__name__)

# JSM-specific metadata field keys
FIELD_CUSTOMER_REQUEST_TYPE = "customer_request_type"
FIELD_ORGANIZATIONS = "organizations"
FIELD_SLA_STATUS = "sla_status"


def extract_customer_request_type(issue: Issue) -> str | None:
    """Extracts the Customer Request Type from a Jira Service Management issue.

    In Jira Cloud / Server JSM, request type may be stored in a custom field
    object (e.g. {'requestType': {'name': '...'}, ...}) or string.
    """
    raw_fields: dict[str, Any] = getattr(issue, "raw", {}).get("fields", {})

    for key, val in raw_fields.items():
        if val is None:
            continue
        # Direct dictionary containing requestType or request type name
        if isinstance(val, dict):
            if "requestType" in val and isinstance(val["requestType"], dict):
                req_name = val["requestType"].get("name")
                if req_name:
                    return str(req_name)
            if "name" in val and "serviceDeskId" in val:
                return str(val["name"])
        # Custom field with key naming
        if "request" in key.lower() and "type" in key.lower() and isinstance(val, str):
            return val

    # Fallback to standard issuetype name if distinct
    issuetype = best_effort_get_field_from_issue(issue, "issuetype")
    if issuetype and hasattr(issuetype, "name"):
        return str(issuetype.name)

    return None


def extract_organizations(issue: Issue) -> list[str]:
    """Extracts customer organizations associated with the JSM issue."""
    # First check fields.organizations
    if hasattr(issue, "fields") and hasattr(issue.fields, "organizations"):
        orgs = getattr(issue.fields, "organizations")
        if isinstance(orgs, list):
            res = []
            for item in orgs:
                if isinstance(item, dict) and "name" in item:
                    res.append(str(item["name"]))
                elif hasattr(item, "name"):
                    res.append(str(item.name))
                elif isinstance(item, str):
                    res.append(item)
            if res:
                return sorted(list(set(res)))

    raw_fields: dict[str, Any] = getattr(issue, "raw", {}).get("fields", {})
    org_names: list[str] = []

    for key, val in raw_fields.items():
        if not val:
            continue
        if ("organization" in key.lower() or key == "organizations") and isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "name" in item:
                    org_names.append(str(item["name"]))
                elif isinstance(item, str):
                    org_names.append(item)

    return sorted(list(set(org_names)))


def extract_sla_info(issue: Issue) -> dict[str, str]:
    """Extracts SLA metrics (e.g., Time to first response, Time to resolution).

    Returns a mapping from SLA name to a status description (e.g. 'Breached', 'Met', 'In Progress').
    """
    raw_fields: dict[str, Any] = getattr(issue, "raw", {}).get("fields", {})
    slas: dict[str, str] = {}

    for _, val in raw_fields.items():
        if not isinstance(val, dict):
            continue
        # JSM SLA fields typically have 'ongoingCycle' or 'completedCycles'
        if "ongoingCycle" in val or "completedCycles" in val:
            sla_name = val.get("name")
            if not sla_name:
                continue

            ongoing = val.get("ongoingCycle")
            if ongoing and isinstance(ongoing, dict):
                breached = ongoing.get("breached", False)
                slas[str(sla_name)] = "Breached" if breached else "In Progress"
                continue

            completed = val.get("completedCycles")
            if completed and isinstance(completed, list) and completed:
                last_cycle = completed[-1]
                if isinstance(last_cycle, dict):
                    breached = last_cycle.get("breached", False)
                    slas[str(sla_name)] = "Breached" if breached else "Met"
                    continue

    return slas


def get_jsm_comment_strs(
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    include_internal_comments: bool = True,
) -> list[str]:
    """Processes comments for Jira Service Management.

    Detects internal agent-only notes vs public customer comments.
    If include_internal_comments is True, tags internal comments with '[Internal Note]'.
    If False, excludes internal comments.
    """
    if not hasattr(issue, "fields") or not hasattr(issue.fields, "comment"):
        return []

    comment_strs: list[str] = []
    comments = getattr(issue.fields.comment, "comments", [])

    for comment in comments:
        try:
            # Check author against email blacklist
            if (
                hasattr(comment, "author")
                and hasattr(comment.author, "emailAddress")
                and comment.author.emailAddress in comment_email_blacklist
            ):
                continue

            # Extract body text
            if isinstance(comment.body, str):
                body_text = comment.body
            elif hasattr(comment, "raw") and "body" in comment.raw:
                body_text = extract_text_from_adf(comment.raw["body"])
            else:
                body_text = str(getattr(comment, "body", ""))

            if not body_text.strip():
                continue

            # Determine if comment is internal
            raw_comment = getattr(comment, "raw", {})
            # Atlassian JSM jsdPublic: False means internal note
            is_public = raw_comment.get("jsdPublic", True)

            if not is_public:
                if not include_internal_comments:
                    continue
                body_text = f"[Internal Note] {body_text}"

            comment_strs.append(body_text)
        except Exception as e:
            logger.error("Failed to process JSM comment: %s", e)
            continue

    return comment_strs
