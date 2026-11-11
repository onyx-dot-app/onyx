from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    BaseConnector,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    NormalizationResult,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_desk.client import JiraServiceManagementClient
from onyx.connectors.jira_service_desk.models import (
    JSMCustomerRequest,
    JSMServiceDesk,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


def _parse_iso_utc(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


class JiraServiceManagementConnector(
    LoadConnector,
    PollConnector,
    SlimConnector,
    BaseConnector,
):
    """
    Onyx Connector for Jira Service Management (JSM).
    Extracts customer requests, service desk tickets, and metadata, transforming them
    into searchable Onyx Document representations.
    """

    def __init__(
        self,
        jira_base_url: str | None = None,
        project_key: str | None = None,
        batch_size: int = 50,
    ) -> None:
        self.jira_base_url = (jira_base_url or "").rstrip("/")
        self.project_key = project_key
        self.batch_size = batch_size
        self.client: JiraServiceManagementClient | None = None

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        user_email = (
            credentials.get("jira_user_email")
            or credentials.get("user_email")
            or credentials.get("email")
        )
        api_token = (
            credentials.get("jira_api_token")
            or credentials.get("api_token")
            or credentials.get("token")
        )
        base_url = credentials.get("jira_base_url") or self.jira_base_url

        if not base_url or not user_email or not api_token:
            raise ConnectorValidationError(
                "Missing required credentials for Jira Service Management. "
                "Must provide jira_base_url, jira_user_email, and jira_api_token."
            )

        self.jira_base_url = base_url.rstrip("/")
        self.client = JiraServiceManagementClient(
            base_url=self.jira_base_url,
            user_email=user_email,
            api_token=api_token,
            project_key=self.project_key,
        )
        return credentials

    @override
    def validate_connector_settings(self) -> None:
        if not self.client:
            raise ConnectorMissingCredentialError("Jira Service Management")
        self.client.get_service_desks()

    def _transform_to_document(self, request: JSMCustomerRequest) -> Document:
        """Converts a JSM Customer Request into an Onyx Document model."""
        portal_url = (
            f"{self.jira_base_url}/servicedesk/customer/portal/{request.service_desk_id}/{request.issue_key}"
            if request.service_desk_id
            else f"{self.jira_base_url}/browse/{request.issue_key}"
        )

        content_body = (
            f"Ticket: {request.issue_key}\n"
            f"Summary: {request.summary}\n"
            f"Status: {request.status or 'Unknown'}\n\n"
            f"Description:\n{request.description or 'No description provided.'}"
        )

        dt_updated = (
            _parse_iso_utc(request.created_date)
            if request.created_date
            else datetime.now(timezone.utc)
        )

        return Document(
            id=portal_url,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"[{request.issue_key}] {request.summary}",
            metadata={
                "issue_key": request.issue_key,
                "issue_id": request.issue_id,
                "service_desk_id": request.service_desk_id or "",
                "status": request.status or "Unknown",
                "created_date": request.created_date or "",
            },
            sections=[
                TextSection(
                    text=content_body,
                    link=portal_url,
                )
            ],
            doc_updated_at=dt_updated,
            doc_created_at=dt_updated,
            title=f"[{request.issue_key}] {request.summary}",
        )

    @override
    def load_from_state(self) -> GenerateDocumentsOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("Jira Service Management")

        service_desks = self.client.get_service_desks()
        doc_batch: list[Document | HierarchyNode] = []

        for desk in service_desks:
            for req in self.client.paginate_customer_requests(
                service_desk_id=desk.id,
                batch_size=self.batch_size,
            ):
                doc_batch.append(self._transform_to_document(req))
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    @override
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("Jira Service Management")

        service_desks = self.client.get_service_desks()
        doc_batch: list[Document | HierarchyNode] = []

        for desk in service_desks:
            for req in self.client.paginate_customer_requests(
                service_desk_id=desk.id,
                start_epoch=int(start),
                batch_size=self.batch_size,
            ):
                doc_batch.append(self._transform_to_document(req))
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("Jira Service Management")

        service_desks = self.client.get_service_desks()
        slim_batch: list[SlimDocument | HierarchyNode] = []

        for desk in service_desks:
            for req in self.client.paginate_customer_requests(
                service_desk_id=desk.id,
                start_epoch=int(start) if start else None,
                batch_size=self.batch_size,
            ):
                portal_url = (
                    f"{self.jira_base_url}/servicedesk/customer/portal/{req.service_desk_id}/{req.issue_key}"
                    if req.service_desk_id
                    else f"{self.jira_base_url}/browse/{req.issue_key}"
                )
                dt_created = (
                    _parse_iso_utc(req.created_date) if req.created_date else None
                )
                slim_batch.append(
                    SlimDocument(
                        id=portal_url,
                        doc_created_at=dt_created,
                        doc_updated_at=dt_created,
                    )
                )
                if len(slim_batch) >= self.batch_size:
                    yield slim_batch
                    slim_batch = []

        if slim_batch:
            yield slim_batch

    @classmethod
    @override
    def normalize_url(cls, url: str) -> NormalizationResult:
        return NormalizationResult(normalized_url=url.strip(), use_default=False)
