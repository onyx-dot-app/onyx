import io
import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import IO
from urllib.parse import quote

from pydantic import Field

from onyx.configs.app_configs import EGNYTE_CLIENT_ID
from onyx.configs.app_configs import EGNYTE_CLIENT_SECRET
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import detect_encoding
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_accepted_file_ext
from onyx.file_processing.extract_file_text import is_text_file_extension
from onyx.file_processing.extract_file_text import OnyxExtensionType
from onyx.file_processing.extract_file_text import read_text_file
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries


logger = setup_logger()

_EGNYTE_API_BASE = "https://{domain}.egnyte.com/pubapi/v1"
_EGNYTE_APP_BASE = "https://{domain}.egnyte.com"


def _parse_last_modified(last_modified: str) -> datetime:
    return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
        tzinfo=timezone.utc
    )


def _process_egnyte_file(
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
    if not is_accepted_file_ext(
        extension, OnyxExtensionType.Plain | OnyxExtensionType.Document
    ):
        logger.warning(f"Skipping file '{file_name}' with extension '{extension}'")
        return None

    # Extract text content based on file type
    if is_text_file_extension(file_name):
        encoding = detect_encoding(file_content)
        file_content_raw, file_metadata = read_text_file(
            file_content, encoding=encoding, ignore_onyx_metadata=False
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
        metadata["lock_owner"] = (
            f"{lock_info.get('first_name', '')} {lock_info.get('last_name', '')}"
        )

    # Create the document owners
    primary_owner = None
    if uploaded_by := file_metadata.get("uploaded_by"):
        primary_owner = BasicExpertInfo(
            email=uploaded_by,  # Using username as email since that's what we have
        )

    # Create the document
    return Document(
        id=f"egnyte-{file_metadata['entry_id']}",
        sections=[TextSection(text=file_content_raw.strip(), link=web_url)],
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


class EgnyteConnector(LoadConnector, PollConnector, OAuthConnector):
    class AdditionalOauthKwargs(OAuthConnector.AdditionalOauthKwargs):
        egnyte_domain: str = Field(
            title="Egnyte Domain",
            description=(
                "The domain for the Egnyte instance "
                "(e.g. 'company' for company.egnyte.com)"
            ),
        )

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
        return DocumentSource.EGNYTE

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
    ) -> str:
        if not EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)

        callback_uri = get_oauth_callback_uri(base_domain, "egnyte")
        return (
            f"https://{oauth_kwargs.egnyte_domain}.egnyte.com/puboauth/token"
            f"?client_id={EGNYTE_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&scope=Egnyte.filesystem"
            f"&state={state}"
            f"&response_type=code"
        )

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],
    ) -> dict[str, Any]:
        if not EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")
        if not EGNYTE_CLIENT_SECRET:
            raise ValueError("EGNYTE_CLIENT_SECRET environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)

        # Exchange code for token
        url = f"https://{oauth_kwargs.egnyte_domain}.egnyte.com/puboauth/token"
        redirect_uri = get_oauth_callback_uri(base_domain, "egnyte")

        data = {
            "client_id": EGNYTE_CLIENT_ID,
            "client_secret": EGNYTE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "scope": "Egnyte.filesystem",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url=url,
            data=data,
            headers=headers,
            # try a lot faster since this is a realtime flow
            backoff=0,
            delay=0.1,
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()
        return {
            "domain": oauth_kwargs.egnyte_domain,
            "access_token": token_data["access_token"],
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.domain = credentials["domain"]
        self.access_token = credentials["access_token"]
        return None

    def _get_files_list(
        self,
        path: str,
    ) -> Generator[dict[str, Any], None, None]:
        if not self.access_token or not self.domain:
            raise ConnectorMissingCredentialError("Egnyte")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        params: dict[str, Any] = {
            "list_content": True,
        }

        url_encoded_path = quote(path or "")
        url = f"{_EGNYTE_API_BASE.format(domain=self.domain)}/fs/{url_encoded_path}"
        response = request_with_retries(
            method="GET", url=url, headers=headers, params=params
        )
        if not response.ok:
            raise RuntimeError(f"Failed to fetch files from Egnyte: {response.text}")

        data = response.json()

        # Yield files from current directory
        for file in data.get("files", []):
            yield file

        # Recursively traverse folders
        for folder in data.get("folders", []):
            yield from self._get_files_list(folder["path"])

    def _should_index_file(
        self,
        file: dict[str, Any],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> bool:
        """Return True if file should be included based on filters."""
        if file["is_folder"]:
            return False

        file_modified = _parse_last_modified(file["last_modified"])
        if start_time and file_modified < start_time:
            return False
        if end_time and file_modified > end_time:
            return False

        return True

    def _process_files(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Generator[list[Document], None, None]:
        current_batch: list[Document] = []

        # Iterate through yielded files and filter them
        for file in self._get_files_list(self.folder_path):
            if not self._should_index_file(file, start_time, end_time):
                logger.debug(f"Skipping file '{file['path']}'.")
                continue

            try:
                # Set up request with streaming enabled
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                }
                url_encoded_path = quote(file["path"])
                url = f"{_EGNYTE_API_BASE.format(domain=self.domain)}/fs-content/{url_encoded_path}"
                response = request_with_retries(
                    method="GET",
                    url=url,
                    headers=headers,
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
                doc = _process_egnyte_file(
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

            except Exception:
                logger.exception(f"Failed to process file {file['path']}")
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
