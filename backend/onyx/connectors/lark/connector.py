import os
from collections.abc import Generator
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

_LARK_API_BASE_URL = "https://open.larksuite.com/open-apis"
_LARK_CALL_TIMEOUT = 30
_LARK_PAGE_SIZE = 200
_LARK_DOCUMENT_TYPES = frozenset({"doc", "docx"})

logger = setup_logger()


class LarkApiError(ConnectionError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class LarkFile(BaseModel):
    token: str
    name: str
    type: str
    url: str | None = None
    created_time: str | None = None
    modified_time: str | None = None
    parent_token: str | None = None


class LarkApiClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_access_token: str | None = None
        self._base_url = os.environ.get("LARK_API_BASE_URL", _LARK_API_BASE_URL).rstrip(
            "/"
        )

    def authenticate(self) -> None:
        response = rl_requests.post(
            f"{self._base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=_LARK_CALL_TIMEOUT,
        )
        payload = self._parse_response(response)
        tenant_access_token = payload.get("tenant_access_token")
        if not isinstance(tenant_access_token, str) or not tenant_access_token:
            raise LarkApiError("Lark did not return a tenant access token")
        self._tenant_access_token = tenant_access_token

    def list_files(
        self,
        folder_token: str | None,
        page_token: str | None = None,
        page_size: int = _LARK_PAGE_SIZE,
    ) -> tuple[list[LarkFile], str | None]:
        params: dict[str, str | int] = {"page_size": page_size}
        if folder_token:
            params["folder_token"] = folder_token
        if page_token:
            params["page_token"] = page_token

        data = self._get("drive/v1/files", params)
        raw_files = data.get("files", [])
        if not isinstance(raw_files, list):
            raise LarkApiError("Lark returned an invalid files response")

        files = [LarkFile.model_validate(file) for file in raw_files]
        has_more = data.get("has_more", False)
        next_page_token = data.get("page_token")
        if has_more and isinstance(next_page_token, str) and next_page_token:
            return files, next_page_token
        return files, None

    def get_document_content(self, file: LarkFile) -> str:
        token = quote(file.token, safe="")
        if file.type == "docx":
            data = self._get(f"docx/v1/documents/{token}/raw_content")
            content = data.get("content")
        elif file.type == "doc":
            data = self._get(f"doc/v2/{token}/raw_content")
            content = data.get("raw_content")
        else:
            raise ValueError(f"Unsupported Lark document type: {file.type}")

        if content is None:
            return ""
        if not isinstance(content, str):
            raise LarkApiError("Lark returned non-text document content")
        return content

    def _get(
        self, endpoint: str, params: dict[str, str | int] | None = None
    ) -> dict[str, Any]:
        if not self._tenant_access_token:
            raise ConnectorMissingCredentialError("Lark")

        response = rl_requests.get(
            f"{self._base_url}/{endpoint.lstrip('/')}",
            headers={"Authorization": f"Bearer {self._tenant_access_token}"},
            params=params,
            timeout=_LARK_CALL_TIMEOUT,
        )
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as e:
            raise LarkApiError(
                f"Lark returned invalid JSON (HTTP {response.status_code})",
                status_code=response.status_code,
            ) from e

        if not isinstance(payload, dict):
            raise LarkApiError(
                "Lark returned an invalid response payload",
                status_code=response.status_code,
            )

        error_code = payload.get("code")
        error_message = payload.get("msg") or payload.get("message")
        if response.status_code >= 300 or error_code not in (None, 0):
            message = (
                str(error_message)
                if error_message
                else f"Lark API request failed (HTTP {response.status_code})"
            )
            raise LarkApiError(
                message,
                status_code=response.status_code,
                error_code=error_code if isinstance(error_code, int) else None,
            )

        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise LarkApiError(
                "Lark returned an invalid response data payload",
                status_code=response.status_code,
            )
        return data


def _parse_lark_timestamp(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None

    try:
        numeric_timestamp = float(timestamp)
    except ValueError:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None:
            return parsed_timestamp.replace(tzinfo=timezone.utc)
        return parsed_timestamp.astimezone(timezone.utc)

    if numeric_timestamp >= 100_000_000_000:
        numeric_timestamp /= 1000
    return datetime.fromtimestamp(numeric_timestamp, tz=timezone.utc)


class LarkConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        folder_token: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.folder_token = folder_token.strip() if folder_token else None
        self.batch_size = batch_size
        self._client: LarkApiClient | None = None

    @property
    def client(self) -> LarkApiClient:
        if self._client is None:
            raise ConnectorMissingCredentialError("Lark")
        return self._client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        app_id = credentials.get("lark_app_id")
        app_secret = credentials.get("lark_app_secret")
        if not isinstance(app_id, str) or not app_id.strip():
            raise ConnectorMissingCredentialError("Lark app ID")
        if not isinstance(app_secret, str) or not app_secret.strip():
            raise ConnectorMissingCredentialError("Lark app secret")

        self._client = LarkApiClient(app_id.strip(), app_secret.strip())
        self._client.authenticate()
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return batch_generator(self._generate_documents(), self.batch_size)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return batch_generator(self._generate_documents(start, end), self.batch_size)

    def validate_connector_settings(self) -> None:
        try:
            self.client.list_files(self.folder_token, page_size=1)
        except LarkApiError as e:
            if e.status_code == 401 or e.error_code in {99991661, 99991663}:
                raise CredentialInvalidError(
                    "Lark app ID or app secret is invalid."
                ) from e
            if e.status_code == 403:
                raise InsufficientPermissionsError(
                    "The Lark app does not have permission to list Drive files."
                ) from e
            if e.status_code == 404:
                raise ConnectorValidationError(
                    "The configured Lark folder was not found or is not accessible."
                ) from e
            raise UnexpectedValidationError(
                f"Unable to validate Lark connector settings: {e}"
            ) from e

    def _generate_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Generator[Document, None, None]:
        for file in self._iter_documents():
            try:
                updated_at = _parse_lark_timestamp(file.modified_time)
            except (TypeError, ValueError, OverflowError) as e:
                logger.warning(
                    "Skipping Lark document %s with invalid modified time %r: %s",
                    file.token,
                    file.modified_time,
                    e,
                )
                continue

            if start is not None and end is not None:
                if updated_at is None or not start < updated_at.timestamp() <= end:
                    continue

            try:
                content = self.client.get_document_content(file)
            except LarkApiError as e:
                logger.warning("Skipping Lark document %s: %s", file.token, e)
                continue

            yield self._to_document(file, content, updated_at)

    def _iter_documents(self) -> Iterator[LarkFile]:
        folders_to_visit: list[str | None] = [self.folder_token]
        visited_folders: set[str] = set()
        yielded_documents: set[tuple[str, str]] = set()

        while folders_to_visit:
            folder_token = folders_to_visit.pop()
            if folder_token is not None:
                if folder_token in visited_folders:
                    continue
                visited_folders.add(folder_token)

            for file in self._iter_files_in_folder(folder_token):
                if file.type == "folder":
                    folders_to_visit.append(file.token)
                    continue
                if file.type not in _LARK_DOCUMENT_TYPES:
                    continue

                document_key = (file.type, file.token)
                if document_key in yielded_documents:
                    continue
                yielded_documents.add(document_key)
                yield file

    def _iter_files_in_folder(self, folder_token: str | None) -> Iterator[LarkFile]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            files, next_page_token = self.client.list_files(
                folder_token, page_token=page_token
            )
            yield from files

            if not next_page_token:
                return
            if next_page_token in seen_page_tokens:
                raise LarkApiError("Lark returned a repeated pagination token")
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

    @staticmethod
    def _to_document(
        file: LarkFile,
        content: str,
        updated_at: datetime | None,
    ) -> Document:
        text = "\n\n".join(part for part in (file.name, content) if part).strip()
        return Document(
            id=f"lark-{file.type}-{file.token}",
            sections=[TextSection(link=file.url, text=text)],
            source=DocumentSource.LARK,
            semantic_identifier=file.name or file.token,
            doc_updated_at=updated_at,
            metadata={
                "lark_file_token": file.token,
                "lark_file_type": file.type,
                "created_time": file.created_time or "",
            },
        )
