"""Helpers for Jira Service Management (JSM) specific issue fields.

JSM stores its domain data (customer request type, organizations, SLAs) in
custom fields whose IDs (``customfield_XXXXX``) differ between Jira instances.
The field *display names* are stable though, so IDs are discovered by name at
runtime and extraction falls back to structural value detection when discovery
is unavailable. Nothing here is instance-specific.
"""

from dataclasses import dataclass
from typing import Any

from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Metadata keys stamped onto the resulting Document
FIELD_CUSTOMER_REQUEST_TYPE = "customer_request_type"
FIELD_ORGANIZATIONS = "organizations"
FIELD_SLA_STATUS = "sla_status"

# JSM custom fields identified by their (stable) display names.
CUSTOMER_REQUEST_TYPE_FIELD_NAME = "Customer Request Type"
ORGANIZATIONS_FIELD_NAME = "Organizations"

# Regardless of the instance-specific field ID or the admin-defined SLA name,
# SLA field values always carry one of these keys.
_SLA_KEYS = ("ongoingCycle", "completedCycles")


@dataclass
class JsmFieldMap:
    """Best-effort mapping of JSM field names to instance-specific field IDs."""

    customer_request_type: str | None = None
    organizations: str | None = None


def discover_jsm_fields(jira_client: JiraSourceOperations | Any) -> JsmFieldMap:
    """Discover JSM custom field IDs by their display names.

    Best effort: if the fields endpoint is unavailable, an empty map is
    returned and the extractors fall back to structural value detection.
    """
    try:
        # Production uses the credential-scoped gateway; legacy test fixtures
        # may still expose the old SDK fields() method.
        all_fields = (
            jira_client.list_fields()
            if isinstance(jira_client, JiraSourceOperations)
            else jira_client.fields()
        )
    except Exception:
        logger.warning(
            "Unable to list Jira fields for JSM field discovery; "
            "falling back to structural detection."
        )
        return JsmFieldMap()

    field_map = JsmFieldMap()
    for field in all_fields:
        try:
            name = field.get("name")
            field_id = field.get("id")
        except AttributeError:
            continue
        if not name or not field_id:
            continue
        if name == CUSTOMER_REQUEST_TYPE_FIELD_NAME:
            field_map.customer_request_type = field_id
        elif name == ORGANIZATIONS_FIELD_NAME:
            field_map.organizations = field_id
    return field_map


def _issue_raw_fields(issue: Any) -> dict[str, Any]:
    """JSM accepts the current Jira raw-JSON gateway and legacy SDK fixtures."""
    raw: Any = issue if isinstance(issue, dict) else getattr(issue, "raw", None)
    if not isinstance(raw, dict):
        return {}
    fields = raw.get("fields")
    return fields if isinstance(fields, dict) else {}


def _get_raw_field(issue: Any, field_id: str) -> Any:
    return _issue_raw_fields(issue).get(field_id)


def _raw_field_values(issue: Any) -> list[Any]:
    return list(_issue_raw_fields(issue).values())


def _name_from_request_type_value(value: dict[str, Any]) -> str | None:
    request_type = value.get("requestType")
    if isinstance(request_type, dict) and request_type.get("name"):
        return str(request_type["name"])
    # Some deployments return {"name": ..., "serviceDeskId": ...}
    if value.get("name") and "serviceDeskId" in value:
        return str(value["name"])
    return None


def extract_customer_request_type(
    issue: Any, field_id: str | None = None
) -> str | None:
    """Extract the JSM customer request type, best effort.

    Jira Cloud returns a ``"<serviceDeskId>/<requestTypeId>"`` string for the
    customer request type field; some deployments return an object with the
    request type embedded. If field discovery failed, raw fields are scanned
    for that object structure.
    """
    if field_id:
        value = _get_raw_field(issue, field_id)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            name = _name_from_request_type_value(value)
            if name:
                return name

    for value in _raw_field_values(issue):
        if isinstance(value, dict):
            name = _name_from_request_type_value(value)
            if name:
                return name
    return None


def _organization_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str) and item:
            names.append(item)
    return names


def _looks_like_organizations(value: Any) -> bool:
    """JSM organization values are lists of ``{"id", "name"}`` dicts."""
    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(item, dict)
        and item.get("name")
        and set(item.keys()) <= {"id", "name"}
        for item in value
    )


def extract_organizations(issue: Any, field_id: str | None = None) -> list[str]:
    """Extract the names of the JSM organizations on the request, best effort."""
    candidates: list[Any] = []
    if field_id:
        value = _get_raw_field(issue, field_id)
        if value is not None:
            candidates.append(value)

    candidates.extend(
        value for value in _raw_field_values(issue) if _looks_like_organizations(value)
    )

    for candidate in candidates:
        names = _organization_names(candidate)
        if names:
            return names
    return []


def extract_sla_info(issue: Any) -> dict[str, str]:
    """Extract SLA statuses keyed by the admin-defined SLA name, best effort.

    An ongoing cycle maps to "In Progress" (or "Breached"), the latest
    completed cycle maps to "Met" (or "Breached").
    """
    slas: dict[str, str] = {}
    for value in _raw_field_values(issue):
        if not isinstance(value, dict) or not any(key in value for key in _SLA_KEYS):
            continue
        sla_name = value.get("name")
        if not sla_name:
            continue

        ongoing = value.get("ongoingCycle")
        if isinstance(ongoing, dict):
            slas[str(sla_name)] = (
                "Breached" if ongoing.get("breached") else "In Progress"
            )
            continue

        completed_cycles = value.get("completedCycles")
        if isinstance(completed_cycles, list) and completed_cycles:
            last_cycle = completed_cycles[-1]
            breached = (
                last_cycle.get("breached", False)
                if isinstance(last_cycle, dict)
                else False
            )
            slas[str(sla_name)] = "Breached" if breached else "Met"
    return slas


def build_jsm_metadata(
    issue: Any, field_map: JsmFieldMap
) -> dict[str, str | list[str]]:
    """Build the JSM specific metadata entries for a ticket document."""
    metadata: dict[str, str | list[str]] = {}

    request_type = extract_customer_request_type(issue, field_map.customer_request_type)
    if request_type:
        metadata[FIELD_CUSTOMER_REQUEST_TYPE] = request_type

    organizations = extract_organizations(issue, field_map.organizations)
    if organizations:
        metadata[FIELD_ORGANIZATIONS] = organizations

    sla_info = extract_sla_info(issue)
    if sla_info:
        metadata[FIELD_SLA_STATUS] = [
            f"{name}: {state}" for name, state in sorted(sla_info.items())
        ]

    return metadata


def get_jsm_comment_strs(
    issue: Any,
    comment_email_blacklist: tuple[str, ...] = (),
    include_internal_comments: bool = False,
) -> list[str]:
    """Extract public JSM comments from raw Jira issues or SDK fixtures.

    The raw JSON gateway returns comment dictionaries; legacy tests may still
    supply Jira SDK resources. Missing or malformed comment data is skipped,
    and internal agent notes are never exposed unless explicitly enabled.
    """
    if isinstance(issue, dict):
        comment_field = _issue_raw_fields(issue).get("comment")
        comments = (
            comment_field.get("comments", [])
            if isinstance(comment_field, dict)
            else []
        )
    else:
        try:
            comments = issue.fields.comment.comments
        except (AttributeError, TypeError):
            return []

    if not isinstance(comments, list):
        return []

    comment_strs: list[str] = []
    for comment in comments:
        try:
            raw_comment: Any = (
                comment if isinstance(comment, dict) else comment.raw
            )
            if not isinstance(raw_comment, dict):
                continue

            author = raw_comment.get("author")
            author_email = (
                author.get("emailAddress")
                if isinstance(author, dict)
                else getattr(getattr(comment, "author", None), "emailAddress", None)
            )
            if author_email in comment_email_blacklist:
                continue

            body = raw_comment.get("body")
            if not isinstance(comment, dict):
                body = getattr(comment, "body", body)
            body_text = (
                body
                if isinstance(body, str)
                else extract_text_from_adf(body if isinstance(body, dict) else None)
            )
            if not body_text or not body_text.strip():
                continue

            is_internal = raw_comment.get("jsdPublic") is False
            if is_internal:
                if not include_internal_comments:
                    continue
                body_text = f"[Internal Note] {body_text}"

            comment_strs.append(body_text)
        except Exception:
            logger.exception("Failed to process JSM comment; skipping it.")
            continue

    return comment_strs
