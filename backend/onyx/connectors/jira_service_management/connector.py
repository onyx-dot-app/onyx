"""Jira Service Management Connector.

Connects to Jira Service Management (JSM) to index service desk tickets,
customer requests, comments, and attachment metadata.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorMissingCredentialError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira_service_management.models import (
    JSMAttachment,
    JSMComment,
    JSMCustomer,
    JSMTicket,
    JSMServiceDesk,
)
from onyx.connectors.jira_service_management.utils import (
    JSMAPIError,
    JSMAuthError,
    JSMPaginatedClient,
    JSM_DEFAULT_PAGE_SIZE,
)
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string from Jira API."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_customer(raw: dict[str, Any] | None) -> JSMCustomer | None:
    """Parse customer/requester info from raw Jira API data."""
    if not raw:
        return None
    return JSMCustomer(
        account_id=raw.get("accountId"),
        name=raw.get("name"),
        email=raw.get("emailAddress"),
        display_name=raw.get("displayName"),
        active=raw.get("active", True),
    )


def _parse_comment(raw: dict[str, Any]) -> JSMComment:
    """Parse a comment from raw Jira API data."""
    body = raw.get("body", "")
    # Handle Atlassian Document Format
    if isinstance(body, dict):
        body = _extract_text_from_adf(body)

    author = raw.get("author", {})
    return JSMComment(
        id=str(raw.get("id", "")),
        author_name=author.get("displayName"),
        author_email=author.get("emailAddress"),
        body=body,
        created=_parse_datetime(raw.get("created")),
        updated=_parse_datetime(raw.get("updated")),
        is_public=raw.get("visibility", {}).get("type", "role") != "role",
    )


def _parse_attachment(raw: dict[str, Any]) -> JSMAttachment:
    """Parse attachment metadata from raw Jira API data."""
    author = raw.get("author", {})
    return JSMAttachment(
        id=str(raw.get("id", "")),
        filename=raw.get("filename", ""),
        size=raw.get("size", 0),
        content_type=raw.get("mimeType"),
        author=author.get("displayName"),
        created=_parse_datetime(raw.get("created")),
    )


def _extract_text_from_adf(adf: dict[str, Any] | None) -> str:
    """Extract plain text from Atlassian Document Format."""
    texts: list[str] = []
    if adf is None or "content" not in adf:
        return ""
    for block in adf["content"]:
        if "content" in block:
            for item in block["content"]:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
    return " ".join(texts)


def _raw_to_ticket(raw: dict[str, Any]) -> JSMTicket:
    """Convert raw Jira issue JSON to JSMTicket model."""
    fields = raw.get("fields", {})
    status = fields.get("status", {})
    priority = fields.get("priority")
    resolution = fields.get("resolution")
    issuetype = fields.get("issuetype", {})

    description = fields.get("description", "")
    if isinstance(description, dict):
        description = _extract_text_from_adf(description)

    # Extract request type info if available (JSM-specific)
    request_type_fields = fields.get("requesttype", {})
    request_type_id = None
    request_type_name = None
    if request_type_fields:
        request_type_id = request_type_fields.get("requestTypeId") or str(
            request_type_fields.get("id", "")
        )
        request_type_name = request_type_fields.get("name")

    return JSMTicket(
        id=str(raw.get("id", "")),
        key=raw.get("key", ""),
        summary=fields.get("summary", ""),
        description=description,
        status=status.get("name") if status else None,
        status_category=status.get("statusCategory", {}).get("name") if status else None,
        priority=priority.get("name") if priority else None,
        resolution=resolution.get("name") if resolution else None,
        issue_type=issuetype.get("name") if issuetype else None,
        created=_parse_datetime(fields.get("created")),
        updated=_parse_datetime(fields.get("updated")),
        resolved=_parse_datetime(fields.get("resolutiondate")),
        due_date=_parse_datetime(fields.get("duedate")),
        request_type_id=request_type_id,
        request_type_name=request_type_name,
        reporter=_parse_customer(fields.get("reporter")),
        assignee_name=(
            fields.get("assignee", {}).get("displayName")
            if fields.get("assignee")
            else None
        ),
        assignee_email=(
            fields.get("assignee", {}).get("emailAddress")
            if fields.get("assignee")
            else None
        ),
        labels=fields.get("labels", []),
        components=[c.get("name", "") for c in (fields.get("components") or [])],
        raw=raw,
    )


def _ticket_to_document(
    jira_base_url: str,
    ticket: JSMTicket,
) -> Document | None:
    """Convert a JSMTicket to an Onyx Document."""
    if not ticket.summary and not ticket.description:
        return None

    # Build text content from description + comments + attachments
    content_parts: list[str] = []

    if ticket.description:
        content_parts.append(ticket.description)

    if ticket.comments:
        for comment in ticket.comments:
            if comment.body:
                visibility = "Public" if comment.is_public else "Internal"
                content_parts.append(
                    f"[{visibility} Comment by {comment.author_name or 'Unknown'}]: "
                    f"{comment.body}"
                )

    if ticket.attachments:
        attachment_info = ", ".join(
            f"{a.filename} ({a.content_type or 'unknown type'}, {a.size} bytes)"
            for a in ticket.attachments
        )
        content_parts.append(f"Attachments: {attachment_info}")

    ticket_content = "\n\n".join(content_parts)

    page_url = f"{jira_base_url}/browse/{ticket.key}"

    # Build metadata
    metadata: dict[str, str | list[str]] = {
        "key": ticket.key,
    }
    if ticket.status:
        metadata["status"] = ticket.status
    if ticket.priority:
        metadata["priority"] = ticket.priority
    if ticket.issue_type:
        metadata["issuetype"] = ticket.issue_type
    if ticket.resolution:
        metadata["resolution"] = ticket.resolution
    if ticket.labels:
        metadata["labels"] = ticket.labels
    if ticket.components:
        metadata["components"] = ticket.components
    if ticket.request_type_name:
        metadata["request_type"] = ticket.request_type_name
    if ticket.reporter:
        metadata["reporter"] = ticket.reporter.display_name or ticket.reporter.name or ""
        if ticket.reporter.email:
            metadata["reporter_email"] = ticket.reporter.email
    if ticket.assignee_name:
        metadata["assignee"] = ticket.assignee_name
        if ticket.assignee_email:
            metadata["assignee_email"] = ticket.assignee_email

    # Determine primary owners
    primary_owners: list[str] = []
    if ticket.assignee_name:
        from onyx.connectors.models import BasicExpertInfo

        primary_owners.append(
            BasicExpertInfo(
                display_name=ticket.assignee_name,
                email=ticket.assignee_email,
            ).get_semantic_name()
        )
    elif ticket.reporter:
        from onyx.connectors.models import BasicExpertInfo

        reporter_name = ticket.reporter.display_name or ticket.reporter.name
        if reporter_name:
            primary_owners.append(
                BasicExpertInfo(
                    display_name=reporter_name,
                    email=ticket.reporter.email,
                ).get_semantic_name()
            )

    # Parse updated time for doc_updated_at
    doc_updated_at = None
    if ticket.updated:
        doc_updated_at = ticket.updated

    semantic_identifier = f"{ticket.key}: {ticket.summary}" if ticket.summary else ticket.key
    title = f"{ticket.key} {ticket.summary}" if ticket.summary else ticket.key

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=ticket_content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=semantic_identifier,
        title=title,
        doc_updated_at=doc_updated_at,
        primary_owners=primary_owners or None,
        metadata=metadata,
    )


class JSMConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint for JSM connector incremental sync."""

    offset: int = 0


class JiraServiceManagementConnector(
    CheckpointedConnector[JSMConnectorCheckpoint],
):
    """Connector for Jira Service Management (JSM).

    Indexes service desk tickets (customer requests) including comments
    and attachment metadata. Supports incremental sync via updated timestamp.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        page_size: int = JSM_DEFAULT_PAGE_SIZE,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.project_key = project_key
        self.service_desk_id = service_desk_id
        self._comment_email_blacklist = set(comment_email_blacklist or [])
        self.page_size = min(page_size, 100)
        self._client: JSMPaginatedClient | None = None

    @property
    def client(self) -> JSMPaginatedClient:
        if self._client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._client = JSMPaginatedClient(
            jira_base_url=self.jira_base_url,
            email=credentials.get("jira_user_email"),
            api_token=credentials.get("jira_api_token"),
            personal_token=credentials.get("jira_personal_token"),
        )
        return None

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        """Build JQL query for ticket retrieval with time-based filtering."""
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")

        time_clause = f"updated >= '{start_str}' AND updated <= '{end_str}'"

        clauses: list[str] = [time_clause]

        if self.project_key:
            clauses.insert(0, f'project = "{self.project_key}"')

        return " AND ".join(clauses)

    def _enrich_ticket(self, ticket: JSMTicket) -> JSMTicket:
        """Fetch comments and attachments for a ticket."""
        try:
            raw_comments = self.client.get_ticket_comments(ticket.key)
            ticket.comments = [
                c
                for c in (_parse_comment(rc) for rc in raw_comments)
                if c.author_email not in self._comment_email_blacklist
            ]
        except JSMAPIError as e:
            logger.warning(f"Failed to fetch comments for {ticket.key}: {e}")

        try:
            raw_attachments = self.client.get_ticket_attachments(ticket.key)
            ticket.attachments = [_parse_attachment(ra) for ra in raw_attachments]
        except JSMAPIError as e:
            logger.warning(f"Failed to fetch attachments for {ticket.key}: {e}")

        return ticket

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JSMConnectorCheckpoint,
    ) -> CheckpointOutput[JSMConnectorCheckpoint]:
        jql = self._build_jql(start, end)

        try:
            raw_issues = self.client.search_tickets(
                jql=jql,
                fields="*all",
                page_size=self.page_size,
            )
        except (JSMAuthError, JSMAPIError) as e:
            raise ConnectorMissingCredentialError(
                f"Failed to fetch JSM tickets: {e}"
            ) from e

        current_offset = checkpoint.offset
        new_checkpoint = JSMConnectorCheckpoint(offset=current_offset)

        for i, raw_issue in enumerate(raw_issues):
            if i < current_offset:
                continue

            try:
                ticket = _raw_to_ticket(raw_issue)
                ticket = self._enrich_ticket(ticket)

                document = _ticket_to_document(self.jira_base_url, ticket)
                if document is not None:
                    yield document
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=raw_issue.get("key", "unknown"),
                        document_link=f"{self.jira_base_url}/browse/{raw_issue.get('key', '')}",
                    ),
                    failure_message=f"Failed to process JSM ticket: {e}",
                    exception=e,
                )

            new_checkpoint.offset = i + 1

        new_checkpoint.has_more = False
        return new_checkpoint

    def validate_connector_settings(self) -> None:
        if self._client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        try:
            if self.service_desk_id:
                self.client.get_service_desk_info(self.service_desk_id)
            elif self.project_key:
                # Verify project access by doing a simple search
                self.client.search_tickets(
                    jql=f'project = "{self.project_key}"',
                    page_size=1,
                )
            else:
                # Verify general access
                self.client.get_service_desks()
        except JSMAuthError as e:
            from onyx.connectors.exceptions import CredentialExpiredError

            raise CredentialExpiredError(
                f"JSM credentials are expired or invalid: {e}"
            ) from e
        except JSMAPIError as e:
            from onyx.connectors.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError(
                f"Insufficient permissions for JSM: {e}"
            ) from e

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JSMConnectorCheckpoint:
        return JSMConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JSMConnectorCheckpoint:
        return JSMConnectorCheckpoint(has_more=True)
