"""Helpers for Jira Service Management (JSM) specific issue data.

JSM stores domain data (customer request type, organizations, request
participants, SLAs) in custom fields whose ids (``customfield_XXXXX``) differ
between Jira instances. The field display names are stable, so ids are
discovered by name at runtime; extraction falls back to structural value
detection where discovery is unavailable.
"""

from dataclasses import dataclass
from typing import Any

from jira import JIRA
from jira.resources import Issue

from onyx.configs.app_configs import (
    JIRA_SERVICE_MANAGEMENT_ATTACHMENT_SIZE_THRESHOLD,
)
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions, OnyxMimeTypes
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Document metadata keys for JSM-specific fields.
METADATA_CUSTOMER_REQUEST_TYPE = "customer_request_type"
METADATA_ORGANIZATIONS = "organizations"
METADATA_REQUEST_PARTICIPANTS = "request_participants"
METADATA_SLA_STATUS = "sla_status"

# JSM custom field ids are instance-specific; their display names are stable.
# "Request Type" is the name JSM uses on Server/Data Center.
_CUSTOMER_REQUEST_TYPE_FIELD_NAMES = {"customer request type", "request type"}
_ORGANIZATIONS_FIELD_NAMES = {"organizations"}
_REQUEST_PARTICIPANTS_FIELD_NAMES = {"request participants"}

# JSM SLA field values always carry one of these keys regardless of the SLA's
# admin-defined name or the field's instance-specific id.
_SLA_CYCLE_KEYS = ("ongoingCycle", "completedCycles")

# JSM Server/DC marks internal comments via this entity property rather than
# the cloud-only jsdPublic field.
_SD_PUBLIC_COMMENT_PROPERTY_KEY = "sd.public.comment"

INTERNAL_COMMENT_PREFIX = "[Internal Note]"


@dataclass
class JsmFieldMap:
    """This instance's custom field ids for the standard JSM fields."""

    customer_request_type: str | None = None
    organizations: str | None = None
    request_participants: str | None = None


def discover_jsm_fields(jira_client: JIRA) -> JsmFieldMap:
    """Map stable JSM field display names to this instance's field ids.

    Best effort: a failure to list fields yields an empty map. SLA fields need
    no discovery since they are detected structurally per-issue.
    """
    try:
        all_fields = jira_client.fields()
    except Exception as e:
        logger.warning("Could not list Jira fields for JSM discovery: %s", e)
        return JsmFieldMap()

    field_map = JsmFieldMap()
    for field in all_fields:
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        field_id = field.get("id")
        if not field_name or not field_id:
            continue
        normalized_name = str(field_name).strip().lower()
        if normalized_name in _CUSTOMER_REQUEST_TYPE_FIELD_NAMES:
            field_map.customer_request_type = (
                field_map.customer_request_type or field_id
            )
        elif normalized_name in _ORGANIZATIONS_FIELD_NAMES:
            field_map.organizations = field_map.organizations or field_id
        elif normalized_name in _REQUEST_PARTICIPANTS_FIELD_NAMES:
            field_map.request_participants = field_map.request_participants or field_id
    return field_map


def _get_raw_issue_fields(issue: Issue) -> dict[str, Any]:
    try:
        raw_fields = issue.raw["fields"]
    except (AttributeError, KeyError, TypeError):
        return {}
    return raw_fields if isinstance(raw_fields, dict) else {}


def _extract_request_type_name(value: Any) -> str | None:
    if isinstance(value, str):
        # e.g. "1/37" (serviceDeskId/requestTypeId) or a plain name
        return value
    if isinstance(value, dict):
        request_type = value.get("requestType")
        if isinstance(request_type, dict) and request_type.get("name"):
            return str(request_type["name"])
        if value.get("name"):
            return str(value["name"])
        request_type_id = value.get("requestTypeId")
        service_desk_id = value.get("serviceDeskId")
        if request_type_id and service_desk_id:
            return f"{service_desk_id}/{request_type_id}"
    return None


def _extract_names(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    names = []
    for item in items:
        if isinstance(item, dict):
            # Users carry displayName; organizations carry name
            name = item.get("displayName") or item.get("name")
        else:
            name = item
        if name:
            names.append(str(name))
    return names


def _extract_sla_summaries(raw_fields: dict[str, Any]) -> list[str]:
    """Detect SLA fields structurally: their values are dicts carrying
    ongoingCycle/completedCycles plus the SLA's display name."""
    sla_summaries = []
    for field_value in raw_fields.values():
        if not isinstance(field_value, dict):
            continue
        if not any(key in field_value for key in _SLA_CYCLE_KEYS):
            continue
        name = field_value.get("name")
        if not name:
            continue

        ongoing = field_value.get("ongoingCycle")
        completed = field_value.get("completedCycles")
        last_completed = (
            completed[-1] if isinstance(completed, list) and completed else None
        )
        if isinstance(ongoing, dict):
            status = "Breached" if ongoing.get("breached") else "In Progress"
        elif isinstance(last_completed, dict):
            status = "Breached" if last_completed.get("breached") else "Met"
        else:
            status = "No Active Cycle"
        sla_summaries.append(f"{name}: {status}")
    return sla_summaries


def build_jsm_metadata(
    issue: Issue, field_map: JsmFieldMap
) -> dict[str, str | list[str]]:
    """Extract JSM-specific metadata (customer request type, organizations,
    request participants, SLA status) from an issue's raw fields."""
    metadata: dict[str, str | list[str]] = {}
    raw_fields = _get_raw_issue_fields(issue)

    if field_map.customer_request_type:
        request_type = _extract_request_type_name(
            raw_fields.get(field_map.customer_request_type)
        )
        if request_type:
            metadata[METADATA_CUSTOMER_REQUEST_TYPE] = request_type

    if field_map.organizations:
        organizations = _extract_names(raw_fields.get(field_map.organizations))
        if organizations:
            metadata[METADATA_ORGANIZATIONS] = organizations

    if field_map.request_participants:
        participants = _extract_names(raw_fields.get(field_map.request_participants))
        if participants:
            metadata[METADATA_REQUEST_PARTICIPANTS] = participants

    sla_summaries = _extract_sla_summaries(raw_fields)
    if sla_summaries:
        metadata[METADATA_SLA_STATUS] = sla_summaries

    return metadata


def get_jsm_comment_strs(
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    include_internal_comments: bool = False,
) -> list[str]:
    """Extract comment bodies for an issue.

    JSM flags agent-only comments (internal notes) with jsdPublic=False on
    cloud, or the sd.public.comment entity property on Server/DC. Internal
    comments are skipped unless include_internal_comments is set, in which
    case they are prefixed with "[Internal Note]".
    """
    comment_strs = []
    try:
        comments = issue.fields.comment.comments
    except Exception as e:
        logger.error("Failed to fetch comments due to an error: %s", e)
        comments = []

    for comment in comments:
        try:
            raw = comment.raw if isinstance(comment.raw, dict) else {}
            is_internal = _comment_is_internal(raw)
            if is_internal and not include_internal_comments:
                continue

            if isinstance(comment.body, str):
                body_text = comment.body
            else:
                body_text = extract_text_from_adf(raw.get("body"))

            if not body_text or not body_text.strip():
                continue

            if (
                hasattr(comment, "author")
                and hasattr(comment.author, "emailAddress")
                and comment.author.emailAddress in comment_email_blacklist
            ):
                continue  # Skip adding comment if author's email is in blacklist

            comment_strs.append(
                f"{INTERNAL_COMMENT_PREFIX} {body_text}" if is_internal else body_text
            )
        except Exception as e:
            logger.error("Failed to process comment due to an error: %s", e)
            continue

    return comment_strs


def _comment_is_internal(comment_raw: dict[str, Any]) -> bool:
    if comment_raw.get("jsdPublic") is False:
        return True

    properties = comment_raw.get("properties")
    if isinstance(properties, list):
        for prop in properties:
            if (
                isinstance(prop, dict)
                and prop.get("key") == _SD_PUBLIC_COMMENT_PROPERTY_KEY
            ):
                value = prop.get("value")
                return isinstance(value, dict) and value.get("internal") is True
    return False


def get_issue_attachments(issue: Issue) -> list[dict[str, Any]]:
    """Attachment entries from the issue payload."""
    attachments = _get_raw_issue_fields(issue).get("attachment")
    if not isinstance(attachments, list):
        return []
    return [a for a in attachments if isinstance(a, dict)]


def build_jsm_attachment_doc_id(
    jira_base_url: str, attachment: dict[str, Any]
) -> str | None:
    """Stable document id for an attachment.

    The immutable attachment id is embedded in its content download URL, so the
    id is stable across renames. Falls back to the generic download path when
    only an id is present. Returns None when no id is available.
    """
    content_url = attachment.get("content")
    if isinstance(content_url, str) and content_url:
        return content_url
    attachment_id = attachment.get("id")
    if attachment_id:
        return f"{jira_base_url}/secure/attachment/{attachment_id}/"
    return None


def is_jsm_attachment_admissible(
    attachment: dict[str, Any], allow_images: bool
) -> bool:
    """Metadata-level check shared by the full-index and slim passes so both
    enumerate exactly the same attachments."""
    file_name = attachment.get("filename")
    if not isinstance(file_name, str) or not file_name:
        return False

    size = attachment.get("size")
    if (
        isinstance(size, int)
        and size > JIRA_SERVICE_MANAGEMENT_ATTACHMENT_SIZE_THRESHOLD
    ):
        return False

    media_type = attachment.get("mimeType")
    media_type = media_type if isinstance(media_type, str) else ""
    extension = get_file_ext(file_name)
    if media_type.startswith("image/") or extension in (
        OnyxFileExtensions.IMAGE_EXTENSIONS
    ):
        return allow_images and media_type in OnyxMimeTypes.IMAGE_MIME_TYPES

    return extension in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
