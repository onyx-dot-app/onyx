"""Helpers for Jira Service Management (JSM) specific issue fields.

JSM stores its domain data (customer request type, organizations, SLAs) in
custom fields whose IDs (``customfield_XXXXX``) differ between Jira instances.
The field *display names* are stable though, so IDs are discovered by name at
runtime and extraction falls back to structural value detection when discovery
is unavailable. Nothing here is instance-specific.
"""

from dataclasses import dataclass
from typing import Any

from jira import JIRA
from jira.resources import Issue

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


def discover_jsm_fields(jira_client: JIRA) -> JsmFieldMap:
    """Discover JSM custom field IDs by their display names.

    Best effort: if the fields endpoint is unavailable, an empty map is
    returned and the extractors fall back to structural value detection.
    """
    try:
        all_fields = jira_client.fields()
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


def _get_raw_field(issue: Issue, field_id: str) -> Any:
    try:
        return issue.raw["fields"][field_id]
    except (AttributeError, KeyError, TypeError):
        return None


def _raw_field_values(issue: Issue) -> list[Any]:
    try:
        raw_fields = issue.raw["fields"]
    except (AttributeError, KeyError, TypeError):
        return []
    return list(raw_fields.values()) if isinstance(raw_fields, dict) else []


def _name_from_request_type_value(value: dict[str, Any]) -> str | None:
    request_type = value.get("requestType")
    if isinstance(request_type, dict) and request_type.get("name"):
        return str(request_type["name"])
    # Some deployments return {"name": ..., "serviceDeskId": ...}
    if value.get("name") and "serviceDeskId" in value:
        return str(value["name"])
    return None


def extract_customer_request_type(
    issue: Issue, field_id: str | None = None
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


def extract_organizations(issue: Issue, field_id: str | None = None) -> list[str]:
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


def extract_sla_info(issue: Issue) -> dict[str, str]:
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
    issue: Issue, field_map: JsmFieldMap
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
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    include_internal_comments: bool = False,
) -> list[str]:
    """Extract comment text with JSM internal-note awareness.

    JSM comments carry a ``jsdPublic`` flag: ``False`` marks internal agent
    notes that are not visible to customers. Internal notes are skipped unless
    ``include_internal_comments`` is set; when included, they are tagged with
    an ``[Internal Note]`` prefix so retrieval can distinguish them.
    """
    comment_strs: list[str] = []
    try:
        comments = issue.fields.comment.comments
    except (AttributeError, TypeError):
        return comment_strs

    for comment in comments:
        try:
            if (
                hasattr(comment, "author")
                and hasattr(comment.author, "emailAddress")
                and comment.author.emailAddress in comment_email_blacklist
            ):
                continue

            if isinstance(comment.body, str):
                body_text = comment.body
            else:
                body_text = extract_text_from_adf(comment.raw["body"])

            if not body_text or not body_text.strip():
                continue

            raw_comment = getattr(comment, "raw", None)
            is_internal = (
                isinstance(raw_comment, dict) and raw_comment.get("jsdPublic") is False
            )
            if is_internal:
                if not include_internal_comments:
                    continue
                body_text = f"[Internal Note] {body_text}"

            comment_strs.append(body_text)
        except Exception:
            logger.exception("Failed to process JSM comment; skipping it.")
            continue

    return comment_strs
