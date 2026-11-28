"""Jira Service Management (JSM) Connector for Onyx (#2281)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator

from .client import JSMClient, JSMClientError, JSMRequest


def _parse_iso_ts(value: str) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _request_to_document_dict(req: JSMRequest) -> dict[str, Any]:
    """Build a normalized Onyx-compatible Document payload from a JSM ticket."""
    sections: list[dict[str, Any]] = []
    body_parts = [f"[{req.issue_key}] {req.summary}"]
    if req.status:
        body_parts.append(f"Status: {req.status}")
    if req.description:
        body_parts.append(req.description)

    sections.append({
        "link": req.web_link,
        "text": "\n\n".join(body_parts),
    })

    for comment in req.comments:
        if not comment.body:
            continue
        visibility = "Public" if comment.public else "Internal"
        sections.append({
            "link": f"{req.web_link}#comment-{comment.comment_id}",
            "text": f"Comment ({visibility}) by {comment.author_name}: {comment.body}",
        })

    metadata: dict[str, Any] = {
        "issue_key": req.issue_key,
        "service_desk_id": req.service_desk_id,
        "status": req.status,
    }
    if req.reporter_name:
        metadata["reporter"] = req.reporter_name

    return {
        "id": req.web_link,
        "semantic_identifier": f"{req.issue_key}: {req.summary}",
        "source": "jira_service_management",
        "sections": sections,
        "metadata": metadata,
        "doc_updated_at": req.updated_at or req.created_at,
    }


class JiraServiceManagementConnector:
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

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._client = JSMClient(
            base_url=self.jira_base_url,
            user_email=credentials.get("jira_user_email"),
            api_token=credentials.get("jira_api_token"),
            bearer_token=credentials.get("jira_bearer_token"),
            page_size=self.batch_size,
        )

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

    def load_from_state(self) -> Iterator[list[dict[str, Any]]]:
        return self.poll_source(start=0.0, end=float("inf"))

    def poll_source(self, start: float, end: float) -> Iterator[list[dict[str, Any]]]:
        client = self._require_client()
        desk_id = self._target_desk_id()
        batch: list[dict[str, Any]] = []

        for req in client.iter_requests(
            service_desk_id=desk_id,
            include_comments=True,
            include_internal_comments=self.include_internal_comments,
        ):
            updated_ts = _parse_iso_ts(req.updated_at or req.created_at)
            if updated_ts is not None and (updated_ts < start or updated_ts > end):
                continue
            batch.append(_request_to_document_dict(req))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
