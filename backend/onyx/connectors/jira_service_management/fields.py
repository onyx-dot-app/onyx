"""Service desk fields carried on a Jira issue.

Jira Service Management stores request type, SLA, organization, and participant
values in site-specific custom fields. The field catalog (``GET /field``) maps
each field id to its Service Management schema, so the connector does not
hard-code ``customfield_`` numbers.
"""

from collections.abc import Mapping
from typing import Any

from onyx.configs.app_configs import JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.utils import rich_text
from onyx.connectors.models import Document, TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

SERVICE_DESK_PROJECT_TYPE = "service_desk"

REQUEST_TYPE_CUSTOM = "com.atlassian.servicedesk:vp-origin"
SLA_CUSTOM = "com.atlassian.servicedesk:sd-sla-field"
ORGANIZATION_CUSTOM = "com.atlassian.servicedesk:sd-customer-organizations"
PARTICIPANT_CUSTOM = "com.atlassian.servicedesk:sd-request-participants"

_METADATA_REQUEST_TYPE = "request_type"
_METADATA_CUSTOMER_STATUS = "customer_status"
_METADATA_ORGANIZATIONS = "organizations"
_METADATA_PARTICIPANTS = "request_participants"
_METADATA_SLA_SUMMARY = "sla_summary"
_METADATA_SLA_BREACHED = "sla_breached"
_METADATA_SERVICE_DESK_ID = "service_desk_id"
_METADATA_PORTAL_URL = "customer_portal_url"


def project_type_key(project: Mapping[str, Any]) -> str | None:
    """The project type key (``service_desk``, ``software``, ...) or None."""
    direct = project.get("projectTypeKey")
    if isinstance(direct, str) and direct:
        return direct
    nested = project.get("projectType")
    if isinstance(nested, Mapping):
        key = nested.get("key")
        if isinstance(key, str) and key:
            return key
    return None


def field_custom_by_id(fields: list[dict[str, Any]]) -> dict[str, str]:
    """Field id to the Service Management ``schema.custom`` key, when set."""
    catalog: dict[str, str] = {}
    for field in fields:
        field_id = field.get("id")
        schema = field.get("schema")
        if not isinstance(field_id, str) or not isinstance(schema, dict):
            continue
        custom = schema.get("custom")
        if isinstance(custom, str) and custom:
            catalog[field_id] = custom
    return catalog


def _values_for(
    issue: Mapping[str, Any],
    catalog: Mapping[str, str],
    custom: str,
) -> list[Any]:
    """Values of every issue field whose schema custom key is ``custom``."""
    raw_fields = issue.get("fields")
    if not isinstance(raw_fields, dict):
        return []
    values: list[Any] = []
    for field_id, custom_key in catalog.items():
        if custom_key != custom or field_id not in raw_fields:
            continue
        value = raw_fields[field_id]
        if value is not None:
            values.append(value)
    return values


def _string_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int):
        return str(value)
    return None


def _request_type_parts(value: Any) -> tuple[str | None, str | None, str | None]:
    """Request type name, service desk id, and the customer-visible status."""
    if isinstance(value, str) and value:
        return value, None, None
    if not isinstance(value, dict):
        return None, None, None
    request_type = value.get("requestType")
    name: str | None = None
    service_desk_id: str | None = None
    if isinstance(request_type, dict):
        raw_name = request_type.get("name")
        if isinstance(raw_name, str) and raw_name:
            name = raw_name
        service_desk_id = _string_id(request_type.get("serviceDeskId"))
    customer_status: str | None = None
    current_status = value.get("currentStatus")
    if isinstance(current_status, dict):
        status = current_status.get("status")
        if isinstance(status, str) and status:
            customer_status = status
    return name, service_desk_id, customer_status


def _names(value: Any) -> list[str]:
    """Display names from a string, or from a list of strings and objects."""
    if isinstance(value, str) and value:
        return [value]
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            names.append(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("name", "displayName", "emailAddress"):
            raw = item.get(key)
            if isinstance(raw, str) and raw:
                names.append(raw)
                break
    return names


def _friendly(value: Any) -> str | None:
    if isinstance(value, dict):
        friendly = value.get("friendly")
        if isinstance(friendly, str) and friendly:
            return friendly
    return None


def _sla_parts(value: Any) -> tuple[str | None, bool]:
    """One SLA's searchable summary, and whether any of its cycles breached."""
    if not isinstance(value, dict):
        return None, False
    name = value.get("name")
    label = name if isinstance(name, str) and name else "SLA"
    breached = False
    details: list[str] = []
    ongoing = value.get("ongoingCycle")
    if isinstance(ongoing, dict):
        if ongoing.get("breached") is True:
            breached = True
            details.append("breached")
        remaining = _friendly(ongoing.get("remainingTime"))
        if remaining:
            details.append(f"{remaining} remaining")
    completed = value.get("completedCycles")
    if isinstance(completed, list):
        for cycle in completed:
            if isinstance(cycle, dict) and cycle.get("breached") is True:
                breached = True
    if breached and "breached" not in details:
        details.append("breached")
    if not details:
        return label, breached
    return f"{label} ({', '.join(details)})", breached


def _comment_line(comment: Mapping[str, Any], blacklist: tuple[str, ...]) -> str | None:
    """One comment line, or None for an empty body or a blacklisted author."""
    author = comment.get("author")
    email = author.get("emailAddress") if isinstance(author, dict) else None
    if isinstance(email, str) and email in blacklist:
        return None
    body = rich_text(comment.get("body")).strip()
    if not body:
        return None
    if comment.get("jsdPublic") is False:
        return f"Comment (internal): {body}"
    return f"Comment: {body}"


def _portal_url(jira_base_url: str, service_desk_id: str, issue_key: str) -> str:
    return (
        f"{jira_base_url.rstrip('/')}/servicedesk/customer/portal/"
        f"{service_desk_id}/{issue_key}"
    )


def _issue_fields(issue: Mapping[str, Any]) -> dict[str, Any]:
    raw_fields = issue.get("fields")
    if isinstance(raw_fields, dict):
        return raw_fields
    return {}


def service_desk_text(
    issue: Mapping[str, Any],
    *,
    jira_base_url: str,
    catalog: Mapping[str, str],
    comments: list[dict[str, Any]],
    comment_email_blacklist: tuple[str, ...],
) -> tuple[str, dict[str, str | list[str]]]:
    """Searchable service desk text, and the metadata to store on the document."""
    metadata: dict[str, str | list[str]] = {}
    lines: list[str] = []

    request_values = _values_for(issue, catalog, REQUEST_TYPE_CUSTOM)
    if request_values:
        name, service_desk_id, customer_status = _request_type_parts(request_values[0])
        if name:
            metadata[_METADATA_REQUEST_TYPE] = name
            lines.append(f"Request type: {name}")
        if customer_status:
            metadata[_METADATA_CUSTOMER_STATUS] = customer_status
            lines.append(f"Customer status: {customer_status}")
        if service_desk_id:
            metadata[_METADATA_SERVICE_DESK_ID] = service_desk_id
            issue_key = issue.get("key")
            if isinstance(issue_key, str) and issue_key:
                metadata[_METADATA_PORTAL_URL] = _portal_url(
                    jira_base_url, service_desk_id, issue_key
                )

    organizations: list[str] = []
    for value in _values_for(issue, catalog, ORGANIZATION_CUSTOM):
        organizations.extend(_names(value))
    if organizations:
        metadata[_METADATA_ORGANIZATIONS] = organizations
        lines.append(f"Organizations: {', '.join(organizations)}")

    participants: list[str] = []
    for value in _values_for(issue, catalog, PARTICIPANT_CUSTOM):
        participants.extend(_names(value))
    if participants:
        metadata[_METADATA_PARTICIPANTS] = participants
        lines.append(f"Request participants: {', '.join(participants)}")

    sla_summaries: list[str] = []
    sla_breached = False
    saw_sla = False
    for value in _values_for(issue, catalog, SLA_CUSTOM):
        summary, breached = _sla_parts(value)
        saw_sla = True
        sla_breached = sla_breached or breached
        if summary:
            sla_summaries.append(summary)
    if saw_sla:
        metadata[_METADATA_SLA_BREACHED] = "true" if sla_breached else "false"
    if sla_summaries:
        joined = "; ".join(sla_summaries)
        metadata[_METADATA_SLA_SUMMARY] = joined
        lines.append(f"SLA: {joined}")

    description = rich_text(_issue_fields(issue).get("description")).strip()
    comment_lines: list[str] = []
    for comment in comments:
        line = _comment_line(comment, comment_email_blacklist)
        if line is not None:
            comment_lines.append(line)
    parts = [
        part
        for part in ("\n".join(lines), description, "\n".join(comment_lines))
        if part
    ]
    return "\n\n".join(parts), metadata


def apply_service_desk_fields(
    document: Document,
    issue: Mapping[str, Any],
    *,
    jira_base_url: str,
    catalog: Mapping[str, str],
    comments: list[dict[str, Any]],
    comment_email_blacklist: tuple[str, ...],
) -> None:
    """Set the JSM source, metadata, and text. Keeps the Jira text when the
    service desk text would pass the ticket size limit."""
    document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    text, metadata = service_desk_text(
        issue,
        jira_base_url=jira_base_url,
        catalog=catalog,
        comments=comments,
        comment_email_blacklist=comment_email_blacklist,
    )
    document.metadata.update(metadata)
    if not text:
        return
    if len(text.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
        logger.info(
            "Leaving the Jira text for %s. The service desk text exceeds %s bytes.",
            issue.get("key"),
            JIRA_CONNECTOR_MAX_TICKET_SIZE,
        )
        return
    for section in document.sections:
        if isinstance(section, TextSection):
            section.text = text
            return
