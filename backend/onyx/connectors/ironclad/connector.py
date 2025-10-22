import json
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger


logger = setup_logger()


DEFAULT_BASE_URL = "https://na1.ironcladapp.com/public/api/v1"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
MAX_ATTACHMENTS_PER_RECORD = 5


def _ensure_isoformat(value: datetime) -> str:
    """Render a datetime in ISO-8601 form with a UTC suffix."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    except ValueError:
        logger.debug("Unable to parse datetime value '%s'", value)
        return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(filter(None, (_stringify(item) for item in value)))  # type: ignore[list-item]
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class IroncladConnector(LoadConnector, PollConnector):
    """Connector that indexes Ironclad records and their attachments."""

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        api_base_url: str = DEFAULT_BASE_URL,
        record_types: list[str] | None = None,
        hydrate_entities: bool = True,
        impersonation_email: str | None = None,
        impersonation_user_id: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_attachments: int = MAX_ATTACHMENTS_PER_RECORD,
    ) -> None:
        self.batch_size = batch_size
        self.api_base_url = self._normalize_base_url(api_base_url)
        self.web_base_url = self._derive_web_base_url(self.api_base_url)
        cleaned_types: list[str] = []
        for entry in record_types or []:
            if not entry:
                continue
            cleaned = entry.strip()
            if cleaned:
                cleaned_types.append(cleaned)
        self.record_types = cleaned_types
        self.hydrate_entities = hydrate_entities
        self.impersonation_email = impersonation_email or None
        self.impersonation_user_id = impersonation_user_id or None
        try:
            page_size_int = int(page_size)
        except (TypeError, ValueError):
            page_size_int = DEFAULT_PAGE_SIZE
        self.page_size = min(max(page_size_int, 1), MAX_PAGE_SIZE)
        try:
            max_attachments_int = int(max_attachments)
        except (TypeError, ValueError):
            max_attachments_int = MAX_ATTACHMENTS_PER_RECORD
        self.max_attachments = max(0, max_attachments_int)

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._api_token: str | None = None

    @staticmethod
    def _normalize_base_url(api_base_url: str) -> str:
        normalized = api_base_url.rstrip("/")
        if not normalized.endswith("/public/api/v1"):
            normalized += "/public/api/v1"
        return normalized

    @staticmethod
    def _derive_web_base_url(api_base_url: str) -> str:
        marker = "/public/api/v1"
        if marker in api_base_url:
            return api_base_url[: api_base_url.index(marker)]
        return api_base_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        if self._api_token is None:
            raise ConnectorMissingCredentialError("Ironclad")
        headers: dict[str, str] = {"Authorization": f"Bearer {self._api_token}"}
        if self.impersonation_email:
            headers["x-as-user-email"] = self.impersonation_email
        if self.impersonation_user_id:
            headers["x-as-user-id"] = self.impersonation_user_id
        return headers

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = credentials.get("ironclad_api_token")
        if not api_token:
            raise ConnectorMissingCredentialError("Ironclad")
        self._api_token = api_token
        self._session.headers.update(self._auth_headers())
        return None

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self.api_base_url}{'/' if not path_or_url.startswith('/') else ''}{path_or_url.lstrip('/')}"
        )
        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Ironclad API request error: {exc}") from exc
        if response.status_code == 401:
            raise ConnectorMissingCredentialError("Ironclad")
        if response.status_code >= 400:
            raise RuntimeError(
                f"Ironclad API request failed ({response.status_code}): {response.text}"
            )
        return response

    def _iter_records(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[dict[str, Any], None, None]:
        page = 0
        last_updated_filter: str | None = None
        if start is not None:
            last_updated_filter = _ensure_isoformat(
                datetime.fromtimestamp(start, tz=timezone.utc)
            )

        while True:
            params: dict[str, Any] = {
                "page": page,
                "pageSize": self.page_size,
            }
            if self.record_types:
                params["types"] = ",".join(self.record_types)
            if self.hydrate_entities:
                params["hydrateEntities"] = "true"
            if last_updated_filter:
                params["lastUpdated"] = last_updated_filter
            response = self._request("GET", "/records", params=params)
            payload = response.json()
            records = payload.get("list", [])
            if not records:
                break

            for record in records:
                updated_at = _parse_datetime(record.get("lastUpdated"))
                if start is not None and updated_at and updated_at.timestamp() < start:
                    continue
                if end is not None and updated_at and updated_at.timestamp() > end:
                    continue
                yield record

            if len(records) < self.page_size:
                break
            page += 1

    def _download_attachment(self, href: str) -> bytes | None:
        try:
            response = self._request("GET", href, stream=True)
            return response.content
        except Exception as exc:
            logger.warning("Failed to download Ironclad attachment '%s': %s", href, exc)
            return None

    def _record_app_url(self, record_id: str | None) -> str | None:
        if not record_id:
            return None
        return f"{self.web_base_url}/records/{record_id}"

    def _build_sections(
        self, record: dict[str, Any], record_url: str | None
    ) -> list[TextSection]:
        summary_lines: list[str] = []
        name = record.get("name")
        if name:
            summary_lines.append(f"Record Name: {name}")
        record_type = record.get("type")
        if record_type:
            summary_lines.append(f"Record Type: {record_type}")

        ironclad_id = record.get("ironcladId")
        if ironclad_id:
            summary_lines.append(f"Ironclad ID: {ironclad_id}")

        contract_status = record.get("contractStatus") or {}
        status_value = contract_status.get("status")
        if status_value:
            summary_lines.append(f"Contract Status: {status_value}")
        status_detail = contract_status.get("details")
        if status_detail:
            summary_lines.append(f"Contract Status Details: {status_detail}")

        properties = record.get("properties") or {}
        if properties:
            summary_lines.append("Properties:")
            for key, value in properties.items():
                summary_lines.append(f"- {key}: {_stringify(value)}")

        sections: list[TextSection] = []
        if summary_lines:
            sections.append(TextSection(text="\n".join(summary_lines), link=record_url))

        attachments = record.get("attachments") or {}
        if not isinstance(attachments, dict):
            return sections

        for index, (_, attachment) in enumerate(attachments.items()):
            if index >= self.max_attachments:
                break
            if not isinstance(attachment, dict):
                continue
            href = attachment.get("href")
            filename = attachment.get("filename") or "attachment"
            if not href:
                continue
            attachment_bytes = self._download_attachment(href)
            if attachment_bytes is None:
                continue
            try:
                text = extract_file_text(
                    BytesIO(attachment_bytes),
                    file_name=filename,
                    break_on_unprocessable=False,
                )
            except Exception as exc:
                logger.info(
                    "Ironclad attachment '%s' could not be processed: %s",
                    filename,
                    exc,
                )
                continue
            if not text:
                continue
            attachment_header = f"Attachment: {filename}"
            sections.append(
                TextSection(
                    text=f"{attachment_header}\n\n{text}",
                    link=record_url,
                )
            )
        return sections

    def _record_metadata(
        self,
        record: dict[str, Any],
        record_url: str | None,
    ) -> dict[str, list[str] | str]:
        metadata: dict[str, list[str] | str] = {}
        record_id = record.get("id")
        if record_id:
            metadata["record_id"] = record_id
        if record_url:
            metadata["record_url"] = record_url
        ironclad_id = record.get("ironcladId")
        if ironclad_id:
            metadata["ironclad_id"] = ironclad_id
        record_type = record.get("type")
        if record_type:
            metadata["record_type"] = record_type

        source_data = record.get("source")
        if source_data:
            metadata["source_info"] = _stringify(source_data)

        properties = record.get("properties") or {}
        if properties:
            metadata["properties_json"] = _stringify(properties)

        attachments = record.get("attachments") or {}
        if attachments:
            names = [
                attachment.get("filename") or key
                for key, attachment in attachments.items()
                if isinstance(attachment, dict)
            ]
            cleaned = [name for name in names if name]
            if cleaned:
                metadata["attachments"] = cleaned
        return metadata

    def _record_to_document(
        self,
        record: dict[str, Any],
    ) -> Document | None:
        record_id = record.get("id")
        if not record_id:
            return None
        record_url = self._record_app_url(record_id)
        sections = self._build_sections(record, record_url)
        if not sections:
            return None

        updated_at = _parse_datetime(record.get("lastUpdated"))

        return Document(
            id=f"ironclad_{record_id}",
            sections=sections,
            source=DocumentSource.IRONCLAD,
            semantic_identifier=record.get("name") or record_id,
            metadata=self._record_metadata(record, record_url),
            doc_updated_at=updated_at,
        )

    def _generate_documents(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> GenerateDocumentsOutput:
        batch: list[Document] = []

        for record in self._iter_records(start=start, end=end):
            document = self._record_to_document(record)
            if document is None:
                continue
            batch.append(document)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._generate_documents(start=None, end=None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._generate_documents(start=start, end=end)
