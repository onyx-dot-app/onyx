from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.client import JsmApiError, JsmClient
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        include_internal_comments: bool = True,
        batch_size: int = 50,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.project_key = project_key.upper() if project_key else None
        self.service_desk_id = str(service_desk_id) if service_desk_id is not None else None
        self.include_internal_comments = include_internal_comments
        self.batch_size = batch_size
        self.client: JsmClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        user_email = (
            credentials.get("user_email")
            or credentials.get("email")
            or credentials.get("username")
        )
        api_token = (
            credentials.get("api_token")
            or credentials.get("password")
            or credentials.get("token")
        )
        access_token = credentials.get("access_token")

        if not (api_token or access_token):
            raise ConnectorMissingCredentialError(
                "Jira Service Management requires an API token or access token."
            )

        self.client = JsmClient(
            base_url=self.jira_base_url,
            user_email=user_email,
            api_token=api_token,
            access_token=access_token,
        )
        return None

    def _ensure_client(self) -> JsmClient:
        if self.client is None:
            raise ConnectorMissingCredentialError("JsmClient is not initialized. Call load_credentials first.")
        return self.client

    def _resolve_service_desk_id(self, client: JsmClient) -> str | None:
        if self.service_desk_id:
            return self.service_desk_id

        if self.project_key:
            try:
                desks = client.get_service_desks()
                for d in desks:
                    if d.get("projectKey") == self.project_key or d.get("projectId") == self.project_key:
                        self.service_desk_id = str(d.get("id"))
                        return self.service_desk_id
            except JsmApiError as e:
                logger.warning(f"Could not resolve service desk for project {self.project_key}: {e}")

        return None

    def _extract_request_document(self, req: dict[str, Any], client: JsmClient) -> Document | None:
        issue_key = req.get("issueKey") or req.get("issueId")
        if not issue_key:
            return None

        # Project key filtering if configured
        if self.project_key and not str(issue_key).startswith(f"{self.project_key}-"):
            return None

        field_values = req.get("requestFieldValues", [])
        summary = ""
        description = ""

        for f in field_values:
            field_id = f.get("fieldId", "")
            val = f.get("value")
            if field_id == "summary" and isinstance(val, str):
                summary = val
            elif field_id == "description" and isinstance(val, str):
                description = val

        if not summary:
            summary = f"JSM Request {issue_key}"

        # Status and timestamps
        current_status = req.get("currentStatus", {})
        status_name = current_status.get("status", "Unknown")

        created_info = req.get("createdDate", {})
        epoch_ms = created_info.get("epochMillis")
        if epoch_ms:
            doc_created_at = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        else:
            doc_created_at = datetime.now(timezone.utc)

        status_date_info = current_status.get("statusDate", {})
        status_epoch_ms = status_date_info.get("epochMillis")
        if status_epoch_ms:
            doc_updated_at = datetime.fromtimestamp(status_epoch_ms / 1000.0, tz=timezone.utc)
        else:
            doc_updated_at = doc_created_at

        # Reporter
        reporter_info = req.get("reporter", {})
        reporter_name = reporter_info.get("displayName")
        reporter_email = reporter_info.get("emailAddress")

        # Fetch comments
        comments_text = []
        try:
            comments = client.get_request_comments(
                issue_id_or_key=issue_key,
                limit=50,
                public=None if self.include_internal_comments else True,
            )
            for c in comments:
                body = c.get("body", "").strip()
                if not body:
                    continue
                author = c.get("author", {}).get("displayName", "Unknown")
                is_public = c.get("public", True)
                note_label = "Public Comment" if is_public else "Internal Note"
                comments_text.append(f"[{note_label} by {author}]:\n{body}")
        except JsmApiError:
            raise
        except Exception as e:
            logger.warning(f"Error reading comments for {issue_key}: {e}")
        # Assemble document sections
        sections = [
            TextSection(text=f"Summary: {summary}\nStatus: {status_name}\n\nDescription:\n{description}")
        ]
        if comments_text:
            sections.append(TextSection(text="Comments & Work Notes:\n" + "\n\n".join(comments_text)))

        # Web link
        links = req.get("_links", {})
        web_link = links.get("web") or f"{self.jira_base_url}/browse/{issue_key}"

        metadata = {
            "ticket_id": str(issue_key),
            "status": status_name,
            "service_desk_id": str(req.get("serviceDeskId", "")),
        }
        if reporter_email:
            metadata["reporter_email"] = reporter_email

        primary_owners = (
            [BasicExpertInfo(display_name=reporter_name, email=reporter_email)]
            if (reporter_name or reporter_email)
            else None
        )

        return Document(
            id=web_link,
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=summary,
            metadata=metadata,
            doc_updated_at=doc_updated_at,
            primary_owners=primary_owners,
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        client = self._ensure_client()
        service_desk_id = self._resolve_service_desk_id(client)

        start = 0
        limit = self.batch_size

        while True:
            res = client.get_customer_requests(
                service_desk_id=service_desk_id,
                start=start,
                limit=limit,
            )
            values = res.get("values", [])
            if not values:
                break

            docs: list[Document] = []
            for req in values:
                doc = self._extract_request_document(req, client)
                if doc:
                    docs.append(doc)

            if docs:
                yield docs

            if res.get("isLastPage", True):
                break

            start += len(values)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        client = self._ensure_client()
        service_desk_id = self._resolve_service_desk_id(client)

        start_offset = 0
        limit = self.batch_size
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        while True:
            res = client.get_customer_requests(
                service_desk_id=service_desk_id,
                start=start_offset,
                limit=limit,
            )
            values = res.get("values", [])
            if not values:
                break

            docs: list[Document] = []
            for req in values:
                doc = self._extract_request_document(req, client)
                if doc and doc.doc_updated_at and start_dt <= doc.doc_updated_at <= end_dt:
                    docs.append(doc)

            if docs:
                yield docs

            if res.get("isLastPage", True):
                break

            start_offset += len(values)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        client = self._ensure_client()
        service_desk_id = self._resolve_service_desk_id(client)

        start_offset = 0
        limit = self.batch_size

        while True:
            res = client.get_customer_requests(
                service_desk_id=service_desk_id,
                start=start_offset,
                limit=limit,
            )
            values = res.get("values", [])
            if not values:
                break

            slim_docs: list[SlimDocument] = []
            for req in values:
                issue_key = req.get("issueKey") or req.get("issueId")
                if not issue_key:
                    continue
                if self.project_key and not str(issue_key).startswith(f"{self.project_key}-"):
                    continue

                links = req.get("_links", {})
                web_link = links.get("web") or f"{self.jira_base_url}/browse/{issue_key}"
                slim_docs.append(SlimDocument(id=web_link, perm_sync_data=None))

            if slim_docs:
                yield slim_docs

            if callback:
                callback.progress("jsm_retrieve_all_slim_docs", len(slim_docs))

            if res.get("isLastPage", True):
                break

            start_offset += len(values)
