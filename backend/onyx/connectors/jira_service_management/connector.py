from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any, Optional

from client import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    JiraServiceManagementClient,
)
from models import JSMRequest

try:
    from onyx.configs.constants import DocumentSource
    from onyx.connectors.interfaces import (
        GenerateDocumentsOutput,
        GenerateSlimDocumentOutput,
        LoadConnector,
        PollConnector,
        SecondsSinceUnixEpoch,
        SlimConnector,
    )
    from onyx.connectors.models import (
        Document,
        HierarchyNode,
        SlimDocument,
        TextSection,
    )
    from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
except ImportError:
    class DocumentSource:
        JIRA = "jira"
    class LoadConnector:
        pass
    class PollConnector:
        pass
    class SlimConnector:
        pass
    SecondsSinceUnixEpoch = float
    GenerateDocumentsOutput = Any
    GenerateSlimDocumentOutput = Any
    IndexingHeartbeatInterface = Any

    from pydantic import BaseModel
    class TextSection(BaseModel):
        text: str
        link: Optional[str] = None
    class Document(BaseModel):
        id: str
        sections: list[TextSection]
        source: str
        semantic_identifier: str
        metadata: dict[str, Any]
        doc_updated_at: Optional[datetime] = None
    class SlimDocument(BaseModel):
        id: str
        doc_created_at: Optional[datetime] = None
    HierarchyNode = Any


class JiraServiceManagementConnector(
    LoadConnector,
    PollConnector,
    SlimConnector,
):
    def __init__(
        self,
        project_key: Optional[str] = None,
        service_desk_id: Optional[str] = None,
        include_internal_comments: bool = True,
        batch_size: int = 50,
    ) -> None:
        self.project_key = project_key.upper().strip() if project_key else None
        self.service_desk_id = str(service_desk_id).strip() if service_desk_id else None
        self.include_internal_comments = include_internal_comments
        self.batch_size = batch_size

        self.client: Optional[JiraServiceManagementClient] = None
        self.base_url: str = ""

    def load_credentials(self, credentials: dict[str, Any]) -> Optional[dict[str, Any]]:
        jira_base_url = credentials.get("jira_base_url") or credentials.get("base_url")
        if not jira_base_url:
            raise ConnectorValidationError(
                "Missing 'jira_base_url' in credentials for Jira Service Management."
            )

        self.base_url = jira_base_url.rstrip("/")
        user_email = credentials.get("user_email") or credentials.get("username")
        api_token = credentials.get("api_token") or credentials.get("password")
        pat_token = credentials.get("pat_token") or credentials.get("token")

        self.client = JiraServiceManagementClient(
            base_url=self.base_url,
            user_email=user_email,
            api_token=api_token,
            pat_token=pat_token,
        )
        return credentials

    def _get_client(self) -> JiraServiceManagementClient:
        if not self.client:
            raise ConnectorValidationError(
                "JiraServiceManagementClient is not initialized. Call load_credentials first."
            )
        return self.client

    def _resolve_service_desk_id(self) -> Optional[str]:
        if self.service_desk_id:
            return self.service_desk_id
        if self.project_key:
            client = self._get_client()
            desk = client.get_service_desk_by_key(self.project_key)
            if not desk:
                raise ConnectorValidationError(
                    f"Could not find any Jira Service Desk for project key '{self.project_key}'."
                )
            self.service_desk_id = desk.id
            return self.service_desk_id
        return None

    def validate_connector_settings(self) -> None:
        client = self._get_client()
        client.test_connection()
        if self.project_key and not self.service_desk_id:
            desk = client.get_service_desk_by_key(self.project_key)
            if not desk:
                raise ConnectorValidationError(
                    f"No service desk found for specified project key '{self.project_key}'."
                )

    def _format_ticket_content(self, req: JSMRequest) -> str:
        lines: list[str] = [
            f"Issue: {req.issue_key}",
            f"Summary: {req.summary}",
            f"Status: {req.status}",
        ]

        if req.request_type_name:
            lines.append(f"Request Type: {req.request_type_name}")
        if req.reporter_name or req.reporter_email:
            reporter_str = req.reporter_name or ""
            if req.reporter_email:
                reporter_str += f" ({req.reporter_email})"
            lines.append(f"Reporter: {reporter_str.strip()}")
        if req.assignee_name or req.assignee_email:
            assignee_str = req.assignee_name or ""
            if req.assignee_email:
                assignee_str += f" ({req.assignee_email})"
            lines.append(f"Assignee: {assignee_str.strip()}")
        if req.created_date:
            lines.append(f"Created Date: {req.created_date.isoformat()}")
        if req.updated_date:
            lines.append(f"Updated Date: {req.updated_date.isoformat()}")

        lines.append("")
        lines.append("Description:")
        lines.append(req.description or "No description provided.")

        if req.comments:
            lines.append("")
            lines.append("Comments:")
            for comment in req.comments:
                author = comment.author_name or "Unknown"
                created_str = (
                    comment.created.strftime("%Y-%m-%d %H:%M:%S")
                    if comment.created
                    else ""
                )
                vis = " [Internal]" if not comment.is_public else ""
                lines.append(f"- [{created_str}] {author}{vis}: {comment.body}")

        return "\n".join(lines)

    def _convert_to_document(self, req: JSMRequest) -> Document:
        ticket_url = f"{self.base_url}/browse/{req.issue_key}"
        text_content = self._format_ticket_content(req)

        metadata: dict[str, Any] = {
            "issue_key": req.issue_key,
            "status": req.status,
            "service_desk_id": req.service_desk_id,
        }
        if self.project_key:
            metadata["project"] = self.project_key
        if req.request_type_name:
            metadata["request_type"] = req.request_type_name
        if req.reporter_email:
            metadata["reporter"] = req.reporter_email
        if req.assignee_email:
            metadata["assignee"] = req.assignee_email
        if req.created_date:
            metadata["created_date"] = req.created_date.isoformat()
        if req.updated_date:
            metadata["updated_date"] = req.updated_date.isoformat()

        return Document(
            id=ticket_url,
            sections=[
                TextSection(
                    text=text_content,
                    link=ticket_url,
                )
            ],
            source=DocumentSource.JIRA,
            semantic_identifier=f"{req.issue_key}: {req.summary}",
            metadata=metadata,
            doc_updated_at=req.updated_date,
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        client = self._get_client()
        desk_id = self._resolve_service_desk_id()

        batch: list[Any] = []
        for req in client.iterate_all_requests(
            service_desk_id=desk_id,
            batch_size=self.batch_size,
            include_comments=True,
        ):
            doc = self._convert_to_document(req)
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        client = self._get_client()
        desk_id = self._resolve_service_desk_id()

        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        batch: list[Any] = []
        for req in client.iterate_all_requests(
            service_desk_id=desk_id,
            batch_size=self.batch_size,
            include_comments=True,
        ):
            if req.updated_date:
                if start_dt <= req.updated_date <= end_dt:
                    doc = self._convert_to_document(req)
                    batch.append(doc)
            elif req.created_date and start_dt <= req.created_date <= end_dt:
                doc = self._convert_to_document(req)
                batch.append(doc)

            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def retrieve_all_slim_docs(
        self,
        start: Optional[SecondsSinceUnixEpoch] = None,
        end: Optional[SecondsSinceUnixEpoch] = None,
        callback: Optional[IndexingHeartbeatInterface] = None,
    ) -> GenerateSlimDocumentOutput:
        client = self._get_client()
        desk_id = self._resolve_service_desk_id()

        start_dt = (
            datetime.fromtimestamp(start, tz=timezone.utc) if start is not None else None
        )
        end_dt = (
            datetime.fromtimestamp(end, tz=timezone.utc) if end is not None else None
        )

        batch: list[Any] = []
        for req in client.iterate_all_requests(
            service_desk_id=desk_id,
            batch_size=self.batch_size,
            include_comments=False,
        ):
            if start_dt and req.created_date and req.created_date < start_dt:
                continue
            if end_dt and req.created_date and req.created_date > end_dt:
                continue

            doc_id = f"{self.base_url}/browse/{req.issue_key}"
            batch.append(
                SlimDocument(
                    id=doc_id,
                    doc_created_at=req.created_date,
                )
            )

            if callback:
                callback.progress("Retrieved slim documents", len(batch))

            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
