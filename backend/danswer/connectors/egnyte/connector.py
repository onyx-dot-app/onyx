import io
import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import IO

import requests
from retry import retry

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import OAuthConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.extract_file_text import check_file_ext_is_valid
from danswer.file_processing.extract_file_text import detect_encoding
from danswer.file_processing.extract_file_text import extract_file_text
from danswer.file_processing.extract_file_text import get_file_ext
from danswer.file_processing.extract_file_text import is_text_file_extension
from danswer.file_processing.extract_file_text import read_text_file
from danswer.utils.logger import setup_logger
from danswer.utils.special_types import JSON_ro


logger = setup_logger()

_EGNYTE_LOCALHOST_OVERRIDE = os.getenv("EGNYTE_LOCALHOST_OVERRIDE")
_EGNYTE_BASE_DOMAIN = os.getenv("EGNYTE_DOMAIN")
_EGNYTE_CLIENT_ID = os.getenv("EGNYTE_CLIENT_ID")
_EGNYTE_CLIENT_SECRET = os.getenv("EGNYTE_CLIENT_SECRET")

_EGNYTE_API_BASE = "https://{domain}.egnyte.com/pubapi/v1"
_EGNYTE_APP_BASE = "https://{domain}.egnyte.com"
_TIMEOUT = 60


def _request_with_retries(
    method: str,
    url: str,
    headers: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = _TIMEOUT,
    stream: bool = False,
) -> requests.Response:
    @retry(tries=8, delay=1, backoff=2, logger=logger)
    def _make_request() -> requests.Response:
        if method == "GET":
            response = requests.get(
                url, headers=headers, params=params, timeout=timeout, stream=stream
            )
        elif method == "POST":
            response = requests.post(
                url, headers=headers, json=params, timeout=timeout, stream=stream
            )
        elif method == "PUT":
            response = requests.put(
                url, headers=headers, json=params, timeout=timeout, stream=stream
            )
        elif method == "DELETE":
            response = requests.delete(
                url, headers=headers, params=params, timeout=timeout, stream=stream
            )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response

    return _make_request()


def _parse_last_modified(last_modified: str) -> datetime:
    return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
        tzinfo=timezone.utc
    )


class EgnyteConnector(LoadConnector, PollConnector, OAuthConnector):
    def __init__(
        self,
        folder_path: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.domain = ""  # will always be set in `load_credentials`
        self.folder_path = folder_path or ""  # Root folder if not specified
        self.batch_size = batch_size
        self.access_token: str | None = None

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return "egnyte"

    @classmethod
    def redirect_uri(cls, base_domain: str) -> str:
        if not _EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")
        if not _EGNYTE_BASE_DOMAIN:
            raise ValueError("EGNYTE_DOMAIN environment variable must be set")

        if _EGNYTE_LOCALHOST_OVERRIDE:
            base_domain = _EGNYTE_LOCALHOST_OVERRIDE

        callback_uri = f"{base_domain.strip('/')}/connector/oauth/callback/egnyte"
        return (
            f"https://{_EGNYTE_BASE_DOMAIN}.egnyte.com/puboauth/token"
            f"?client_id={_EGNYTE_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&scope=Egnyte.filesystem"
            # TODO: Add state support
            # f"&state=danswer"
            f"&response_type=code"
        )

    @classmethod
    def code_to_token(cls, code: str) -> JSON_ro:
        if not _EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")
        if not _EGNYTE_CLIENT_SECRET:
            raise ValueError("EGNYTE_CLIENT_SECRET environment variable must be set")
        if not _EGNYTE_BASE_DOMAIN:
            raise ValueError("EGNYTE_DOMAIN environment variable must be set")

        # Exchange code for token
        url = f"https://{_EGNYTE_BASE_DOMAIN}.egnyte.com/puboauth/token"
        data = {
            "client_id": _EGNYTE_CLIENT_ID,
            "client_secret": _EGNYTE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": f"{_EGNYTE_LOCALHOST_OVERRIDE or ''}/connector/oauth/callback/egnyte",
            "scope": "Egnyte.filesystem",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = _request_with_retries(
            method="POST", url=url, data=data, headers=headers
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()
        return {
            "domain": _EGNYTE_BASE_DOMAIN,
            "access_token": token_data["access_token"],
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.domain = credentials["domain"]
        self.access_token = credentials["access_token"]
        return None

    def _get_files_list(
        self,
        path: str,
    ) -> list[dict[str, Any]]:
        if not self.access_token or not self.domain:
            raise ConnectorMissingCredentialError("Egnyte")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        params: dict[str, Any] = {
            "list_content": True,
        }

        url = f"{_EGNYTE_API_BASE.format(domain=self.domain)}/fs/{path or ''}"
        response = _request_with_retries(
            method="GET", url=url, headers=headers, params=params, timeout=_TIMEOUT
        )
        if not response.ok:
            raise RuntimeError(f"Failed to fetch files from Egnyte: {response.text}")

        data = response.json()
        all_files: list[dict[str, Any]] = []

        # Add files from current directory
        all_files.extend(data.get("files", []))

        # Recursively traverse folders
        for item in data.get("folders", []):
            all_files.extend(self._get_files_list(item["path"]))

        return all_files

    def _filter_files(
        self,
        files: list[dict[str, Any]],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        filtered_files = []
        for file in files:
            if file["is_folder"]:
                continue

            file_modified = _parse_last_modified(file["last_modified"])
            if start_time and file_modified < start_time:
                continue
            if end_time and file_modified > end_time:
                continue

            filtered_files.append(file)

        return filtered_files

    def _process_files(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Generator[list[Document], None, None]:
        files = self._get_files_list(self.folder_path)
        files = self._filter_files(files, start_time, end_time)

        current_batch: list[Document] = []
        for file in files:
            try:
                # Set up request with streaming enabled
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                }
                url = f"{_EGNYTE_API_BASE.format(domain=self.domain)}/fs-content/{file['path']}"
                response = _request_with_retries(
                    method="GET",
                    url=url,
                    headers=headers,
                    timeout=_TIMEOUT,
                    stream=True,
                )

                if not response.ok:
                    logger.error(
                        f"Failed to fetch file content: {file['path']} (status code: {response.status_code})"
                    )
                    continue

                # Stream the response content into a BytesIO buffer
                buffer = io.BytesIO()
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        buffer.write(chunk)

                # Reset buffer's position to the start
                buffer.seek(0)

                # Process the streamed file content
                doc = process_egnyte_file(
                    file_metadata=file,
                    file_content=buffer,
                    base_url=_EGNYTE_APP_BASE.format(domain=self.domain),
                    folder_path=self.folder_path,
                )

                if doc is not None:
                    current_batch.append(doc)

                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

            except Exception as e:
                logger.error(f"Failed to process file {file['path']}: {str(e)}")
                continue

        if current_batch:
            yield current_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_files()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._process_files(start_time=start_time, end_time=end_time)


def process_egnyte_file(
    file_metadata: dict[str, Any],
    file_content: IO,
    base_url: str,
    folder_path: str | None = None,
) -> Document | None:
    """Process an Egnyte file into a Document object

    Args:
        file_data: The file data from Egnyte API
        file_content: The raw content of the file in bytes
        base_url: The base URL for the Egnyte instance
        folder_path: Optional folder path to filter results
    """
    # Skip if file path doesn't match folder path filter
    if folder_path and not file_metadata["path"].startswith(folder_path):
        raise ValueError(
            f"File path {file_metadata['path']} does not match folder path {folder_path}"
        )

    file_name = file_metadata["name"]
    extension = get_file_ext(file_name)
    if not check_file_ext_is_valid(extension):
        logger.warning(f"Skipping file '{file_name}' with extension '{extension}'")
        return None

    # Extract text content based on file type
    if is_text_file_extension(file_name):
        encoding = detect_encoding(file_content)
        file_content_raw, file_metadata = read_text_file(
            file_content, encoding=encoding, ignore_danswer_metadata=False
        )
    else:
        file_content_raw = extract_file_text(
            file=file_content,
            file_name=file_name,
            break_on_unprocessable=True,
        )

    # Build the web URL for the file
    web_url = f"{base_url}/navigate/file/{file_metadata['group_id']}"

    # Create document metadata
    metadata: dict[str, str | list[str]] = {
        "file_path": file_metadata["path"],
        "last_modified": file_metadata.get("last_modified", ""),
    }

    # Add lock info if present
    if lock_info := file_metadata.get("lock_info"):
        metadata[
            "lock_owner"
        ] = f"{lock_info.get('first_name', '')} {lock_info.get('last_name', '')}"

    # Create the document owners
    primary_owner = None
    if uploaded_by := file_metadata.get("uploaded_by"):
        primary_owner = BasicExpertInfo(
            email=uploaded_by,  # Using username as email since that's what we have
        )

    # Create the document
    return Document(
        id=f"egnyte-{file_metadata['entry_id']}",
        sections=[Section(text=file_content_raw.strip(), link=web_url)],
        source=DocumentSource.EGNYTE,
        semantic_identifier=file_name,
        metadata=metadata,
        doc_updated_at=(
            _parse_last_modified(file_metadata["last_modified"])
            if "last_modified" in file_metadata
            else None
        ),
        primary_owners=[primary_owner] if primary_owner else None,
    )


if __name__ == "__main__":
    connector = EgnyteConnector()
    connector.load_credentials(
        {
            "domain": os.environ["EGNYTE_DOMAIN"],
            "access_token": os.environ["EGNYTE_ACCESS_TOKEN"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
