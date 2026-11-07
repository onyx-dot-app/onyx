from datetime import datetime
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.models import (
    JSM_ID_PREFIX,
    JsmPollWindow,
    JsmTicketRenderContext,
    extract_expert_info,
    parse_jsm_timestamp,
)
from onyx.connectors.models import Document, TextSection


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = mapping.get(key)
        if val:
            return val
    return None


def extract_field_map(ticket: dict[str, Any]) -> dict[str, Any]:
    # Normalizes field values from Service Desk requestFieldValues arrays or Jira issue fields.
    raw_fields = ticket.get("fields")
    if isinstance(raw_fields, dict):
        return raw_fields
    entries = ticket.get("requestFieldValues")
    if not isinstance(entries, list):
        return {}
    return {
        str(entry["fieldId"]): entry.get("value")
        for entry in entries
        if isinstance(entry, dict) and entry.get("fieldId")
    }


def extract_issue_key(ticket: dict[str, Any]) -> str:
    found = _first_present(ticket, ("issueKey", "key", "issueId"))
    return str(found) if found else ""


def _resolve_dict_field(
    primary: Any, fallback: Any, keys: tuple[str, ...]
) -> str | None:
    target = primary if isinstance(primary, dict) else fallback
    if not isinstance(target, dict):
        return None
    found = _first_present(target, keys)
    return str(found) if found else None


def build_ticket_metadata(
    ticket: dict[str, Any], default_project_key: str | None
) -> dict[str, str | list[str]]:
    # Builds searchable facet metadata for project key, workflow status, priority, and desk identifiers.
    fields = extract_field_map(ticket)
    issue_key = extract_issue_key(ticket)
    project_key = (
        issue_key.split("-", 1)[0]
        if "-" in issue_key
        else (default_project_key or "")
    )
    status_name = _resolve_dict_field(
        ticket.get("currentStatus"), fields.get("status"), ("status", "name")
    )
    priority_name = _resolve_dict_field(
        fields.get("priority"), None, ("name",)
    )
    candidates = {
        "project_key": project_key,
        "status": status_name,
        "priority": priority_name,
        "service_desk_id": ticket.get("serviceDeskId"),
        "request_type_id": ticket.get("requestTypeId"),
    }
    return {
        key: str(val)
        for key, val in candidates.items()
        if val is not None and str(val) != ""
    }


def _extract_primary_text(
    ticket: dict[str, Any], fields: dict[str, Any]
) -> tuple[str, str]:
    issue_key = extract_issue_key(ticket)
    merged = {**ticket, **fields}
    summary = str(merged.get("summary") or "").strip()
    description = str(merged.get("description") or "").strip()
    parts = [part for part in (summary, description) if part]
    body_text = "\n\n".join(parts) if parts else issue_key
    title = f"{issue_key}: {summary}" if summary else issue_key
    return title, body_text


def build_ticket_sections(
    body_text: str, comments: list[dict[str, Any]], ticket_link: str
) -> list[TextSection]:
    sections: list[TextSection] = [TextSection(link=ticket_link, text=body_text)]
    for comment in comments:
        body = comment.get("body")
        if isinstance(body, str) and body.strip():
            sections.append(TextSection(link=ticket_link, text=body.strip()))
    return sections


def resolve_ticket_timestamp(
    ticket: dict[str, Any], fields: dict[str, Any]
) -> datetime | None:
    status_obj = ticket.get("currentStatus")
    status_date = status_obj.get("statusDate") if isinstance(status_obj, dict) else None
    for candidate in (fields.get("updated"), status_date, ticket.get("createdDate")):
        parsed = parse_jsm_timestamp(candidate)
        if parsed is not None:
            return parsed
    return None


def is_within_poll_window(ticket: dict[str, Any], window: JsmPollWindow) -> bool:
    # Checks whether a ticket falls within the requested incremental polling interval.
    updated_dt = resolve_ticket_timestamp(ticket, extract_field_map(ticket))
    if updated_dt is None:
        return True
    after_start = window.start is None or updated_dt >= window.start
    before_end = window.end is None or updated_dt <= window.end
    return after_start and before_end


def convert_ticket_to_document(
    ticket: dict[str, Any], ctx: JsmTicketRenderContext
) -> Document:
    # Converts a Jira Service Management customer request and its comments into an Onyx Document.
    fields = extract_field_map(ticket)
    issue_key = extract_issue_key(ticket)
    title, body_text = _extract_primary_text(ticket, fields)
    web_url = _resolve_dict_field(ticket.get("_links"), None, ("web",))
    ticket_link = web_url or f"{ctx.base_url.rstrip("/")}/browse/{issue_key}"

    reporter = extract_expert_info(
        _first_present({**fields, **ticket}, ("reporter",))
    )
    assignee = extract_expert_info(fields.get("assignee"))

    return Document(
        id=f"{JSM_ID_PREFIX}{issue_key}",
        sections=build_ticket_sections(body_text, ctx.comments, ticket_link),
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=title,
        doc_updated_at=resolve_ticket_timestamp(ticket, fields),
        primary_owners=[reporter] if reporter else None,
        secondary_owners=[assignee] if assignee else None,
        metadata=build_ticket_metadata(ticket, ctx.default_project_key),
    )
