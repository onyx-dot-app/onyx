"""Document shaping shared by the JSM connector's full and slim retrieval."""

from typing import Any

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.jsm.client import (
    fetch_participants,
    fetch_request_type_for_issue,
)
from onyx.connectors.models import BasicExpertInfo, Document, SlimDocument, TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_TICKET_SIZE_BYTES = 100 * 1024

_FIELD_KEY = "key"
_FIELD_SUMMARY = "summary"
_FIELD_DESCRIPTION = "description"
_FIELD_STATUS = "status"
_FIELD_PRIORITY = "priority"
_FIELD_CREATED = "created"
_FIELD_UPDATED = "updated"
_FIELD_ISSUE_TYPE = "issuetype"
_FIELD_PROJECT = "project"
_FIELD_REQUEST_TYPE = "request_type"
_FIELD_SERVICE_DESK = "service_desk"
_FIELD_PARTICIPANTS = "participants"


def _extract_text_from_adf(adf: dict[str, Any] | str | None) -> str:
    """Plain text from an Atlassian Document Format body; plain strings pass
    through for Data Center instances that keep description as text."""
    if adf is None or isinstance(adf, str):
        return adf or ""

    texts: list[str] = []

    def _walk(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            text = node.get("text")
            if text:
                texts.append(text)
        for child in node.get("content") or []:
            if isinstance(child, dict):
                _walk(child)

    _walk(adf)
    return " ".join(texts)


def _best_effort_field(issue: dict[str, Any], field: str) -> Any:
    return issue.get("fields", {}).get(field)


def _user_to_expert_info(user: dict[str, Any] | None) -> BasicExpertInfo | None:
    if not user:
        return None
    display_name = user.get("displayName")
    email = user.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


def process_jsm_issue(
    jsm_base: str,
    issue: dict[str, Any],
    session: Any = None,
) -> Document | None:
    """One JSM issue (a customer request) as an Onyx Document. Returns None
    when the issue body is oversized."""
    issue_key = issue.get(_FIELD_KEY, "")
    fields = issue.get("fields", {})

    description = _extract_text_from_adf(fields.get(_FIELD_DESCRIPTION))
    # Jira Cloud v3 returns comment bodies as ADF documents; Data Center
    # may keep them as plain strings. Both go through the ADF extractor.
    comments = [
        _extract_text_from_adf(comment.get("body"))
        for comment in fields.get("comment", {}).get("comments", [])
        if isinstance(comment, dict)
    ]
    comment_text = "\n".join(f"Comment: {comment}" for comment in comments if comment)
    ticket_content = f"{description}\n{comment_text}".strip()

    if len(ticket_content.encode("utf-8")) > _MAX_TICKET_SIZE_BYTES:
        logger.info(
            "Skipping %s because it exceeds the maximum size of %s bytes.",
            issue_key,
            _MAX_TICKET_SIZE_BYTES,
        )
        return None

    page_url = build_jira_url(jsm_base, issue_key)

    metadata_dict: dict[str, str | list[str]] = {}
    people: set[BasicExpertInfo] = set()

    reporter = _user_to_expert_info(fields.get("reporter"))
    if reporter is not None:
        people.add(reporter)
        metadata_dict["reporter"] = reporter.get_semantic_name()
        if reporter.email:
            metadata_dict["reporter_email"] = reporter.email

    assignee = _user_to_expert_info(fields.get("assignee"))
    if assignee is not None:
        people.add(assignee)
        metadata_dict["assignee"] = assignee.get_semantic_name()
        if assignee.email:
            metadata_dict["assignee_email"] = assignee.email

    metadata_dict["key"] = issue_key

    if status := fields.get(_FIELD_STATUS):
        metadata_dict[_FIELD_STATUS] = status.get("name", "")
    if priority := fields.get(_FIELD_PRIORITY):
        metadata_dict[_FIELD_PRIORITY] = priority.get("name", "")
    if issue_type := fields.get(_FIELD_ISSUE_TYPE):
        metadata_dict[_FIELD_ISSUE_TYPE] = issue_type.get("name", "")
    if project := fields.get(_FIELD_PROJECT):
        metadata_dict["project"] = project.get("key", "")
        metadata_dict["project_name"] = project.get("name", "")

    created = fields.get(_FIELD_CREATED)
    updated = fields.get(_FIELD_UPDATED)

    # JSM-only enrichment: request type and customer participants. Both calls
    # are best effort so a partial JSM setup cannot block indexing.
    if session is not None:
        issue_id = str(issue.get("id", ""))
        request_type = fetch_request_type_for_issue(session, jsm_base, issue_id)
        if request_type:
            metadata_dict[_FIELD_REQUEST_TYPE] = request_type
        participants = fetch_participants(session, jsm_base, issue_id)
        participant_names = [
            participant.get("displayName", "")
            for participant in participants
            if participant.get("displayName")
        ]
        if participant_names:
            metadata_dict[_FIELD_PARTICIPANTS] = participant_names

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JSM,
        semantic_identifier=f"{issue_key}: {fields.get(_FIELD_SUMMARY, '')}",
        title=f"{issue_key} {fields.get(_FIELD_SUMMARY, '')}",
        doc_updated_at=time_str_to_utc(updated) if updated else None,
        doc_created_at=time_str_to_utc(created) if created else None,
        primary_owners=list(people) or None,
        metadata=metadata_dict,
    )


def process_jsm_issue_slim(
    jsm_base: str,
    issue: dict[str, Any],
    external_access: ExternalAccess | None = None,
) -> SlimDocument | None:
    """One JSM issue as a SlimDocument (id, timestamps, external access).

    Returns None for the same oversized issues the full pass skips, so the
    slim/pruning view of the connector matches what full retrieval emits
    instead of resurrecting documents too large to index.
    """
    issue_key = issue.get(_FIELD_KEY, "")
    fields = issue.get("fields", {})
    created = fields.get(_FIELD_CREATED)

    # Same size-eligibility computation as process_jsm_issue.
    description = _extract_text_from_adf(fields.get(_FIELD_DESCRIPTION))
    comment_text = "\n".join(
        f"Comment: {_extract_text_from_adf(comment.get('body'))}"
        for comment in fields.get("comment", {}).get("comments", [])
        if isinstance(comment, dict) and comment.get("body")
    )
    ticket_content = f"{description}\n{comment_text}".strip()
    if len(ticket_content.encode("utf-8")) > _MAX_TICKET_SIZE_BYTES:
        logger.info(
            "Skipping %s because it exceeds the maximum size of %s bytes.",
            issue_key,
            _MAX_TICKET_SIZE_BYTES,
        )
        return None

    return SlimDocument(
        id=build_jira_url(jsm_base, issue_key),
        doc_created_at=time_str_to_utc(created) if created else None,
        external_access=external_access,
    )
