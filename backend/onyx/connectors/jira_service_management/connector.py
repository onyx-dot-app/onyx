"""Jira Service Management (JSM) Connector for Onyx."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import BasicExpertInfo, Document, TextSection

from .client import JSMClient, JSMClientError, JSMRequest


def _parse_iso_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _request_to_document(req: JSMRequest) -> Document:
    """Convert a JSM service desk request into an Onyx Document model."""
    sections: list[TextSection] = []
    body_parts = [f"[{req.issue_key}] {req.summary}"]
    if req.status:
        body_parts.append(f"Status: {req.status}")
    if req.description:
        body_parts.append(req.description)

    sections.append(
        TextSection(
            link=req.web_link,
            text="\n\n".join(body_parts),
        )
    )

    for comment in req.comments:
        if not comment.body:
            continue
        visibility = "Public" if comment.public else "Internal"
        sections.append(
            TextSection(
                link=f"{req.web_link}#comment-{comment.comment_id}",
                text=f"Comment ({visibility}) by {comment.author_name}: {comment.body}",
            )
        )

    metadata: dict[str, str | list[str]] = {
        "issue_key": req.issue_key,
        "service_desk_id": req.service_desk_id,
        "status": req.status,
    }
    if req.reporter_name:
        metadata["reporter"] = req.reporter_name

    primary_owners: list[BasicExpertInfo] | None = None
    if req.reporter_name or req.reporter_email:
        primary_owners = [
            BasicExpertInfo(
                display_name=req.reporter_name or None,
                email=req.reporter_email or None,
            )
        ]

    updated_dt = _parse_iso_dt(req.updated_at or req.created_at)

    return Document(
        id=req.web_link,
        sections=sections,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{req.issue_key}: {req.summary}",
        metadata=metadata,
        doc_updated_at=updated_dt,
        primary_owners=primary_owners,
    )


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Pulls tickets and comments from a specified Jira Service Management project."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        include_internal_comments: bool = False,
        batch_size: int = 50,
    ) -> None:
        self.jira_base_url = jira_base_url
        self.project_key = project_key
        self.service_desk_id = service_desk_id
        self.include_internal_comments = include_internal_comments
        self.batch_size = max(1, int(batch_size))
        self._client: JSMClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._client = JSMClient(
            base_url=self.jira_base_url,
            user_email=credentials.get("jira_user_email"),
            api_token=credentials.get("jira_api_token"),
            bearer_token=credentials.get("jira_bearer_token"),
            page_size=self.batch_size,
        )
        return None

    def set_client(self, client: JSMClient) -> None:
        self._client = client

    def _require_client(self) -> JSMClient:
        if self._client is None:
            raise RuntimeError("Credentials must be loaded before calling JSM connector methods.")
        return self._client

    def _target_desk_id(self) -> str | None:
        if self.service_desk_id:
            return self.service_desk_id
        if self.project_key:
            return self._require_client().resolve_service_desk_id(self.project_key)
        return None

    def validate_connector_settings(self) -> None:
        client = self._require_client()
        if self.project_key:
            client.resolve_service_desk_id(self.project_key)
        else:
            desks = client.list_service_desks()
            if not desks:
                raise JSMClientError("No accessible Jira Service Management desks found.")

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(start=0.0, end=float("inf"))

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        client = self._require_client()
        desk_id = self._target_desk_id()
        batch: list[Document] = []

        for req in client.iter_requests(
            service_desk_id=desk_id,
            include_comments=True,
            include_internal_comments=self.include_internal_comments,
        ):
            updated_dt = _parse_iso_dt(req.updated_at or req.created_at)
            updated_ts = updated_dt.timestamp() if updated_dt is not None else None
            if updated_ts is not None and (updated_ts < start or updated_ts > end):
                continue
            batch.append(_request_to_document(req))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
