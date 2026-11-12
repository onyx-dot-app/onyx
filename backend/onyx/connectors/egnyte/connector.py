import io
import os
from collections.abc import Generator
from datetime import datetime, timezone
from typing import IO, Any

from pydantic import Field

from onyx.configs.app_configs import (
    EGNYTE_CLIENT_ID,
    EGNYTE_CLIENT_SECRET,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.egnyte.models import EgnyteFile
from onyx.connectors.egnyte.source_operations import (
    EgnyteApiError,
    EgnyteSourceOperations,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.file_processing.extract_file_text import (
    detect_encoding,
    extract_file_text,
    get_file_ext,
    read_text_file,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

_EGNYTE_APP_BASE = "https://{domain}.egnyte.com"


def _parse_last_modified(last_modified: str) -> datetime:
    return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
        tzinfo=timezone.utc
    )


def _process_egnyte_file(
    file: EgnyteFile,
    file_content: IO,
    base_url: str,
    folder_path: str | None = None,
) -> Document | None:
    """Process an Egnyte file into a Document object

    Args:
        file: The file metadata from the Egnyte API
        file_content: The raw content of the file in bytes
        base_url: The base URL for the Egnyte instance
        folder_path: Optional folder path to filter results
    """
    # Skip if file path doesn't match folder path filter
    if folder_path and not file.path.startswith(folder_path):
        raise ValueError(
            f"File path {file.path} does not match folder path {folder_path}"
        )

    file_name = file.name
    extension = get_file_ext(file_name)

    # Explicitly excluding image extensions here. TODO: consider allowing images
    if extension not in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS:
        logger.warning("Skipping file '%s' with extension '%s'", file_name, extension)
        return None

    # Extract text content based on file type
    # TODO @wenxi-onyx: convert to extract_text_and_images
    if extension in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS:
        encoding = detect_encoding(file_content)
        file_content_raw, _ = read_text_file(
            file_content, encoding=encoding, ignore_onyx_metadata=False
        )
    else:
        file_content_raw = extract_file_text(
            file=file_content,
            file_name=file_name,
            break_on_unprocessable=True,
        )

    # Build the web URL for the file
    web_url = f"{base_url}/navigate/file/{file.group_id}"

    # Create document metadata
    metadata: dict[str, str | list[str]] = {
        "file_path": file.path,
        "last_modified": file.last_modified,
    }

    if file.lock_info:
        metadata["lock_owner"] = (
            f"{file.lock_info.first_name} {file.lock_info.last_name}"
        )

    # Create the document owners
    primary_owner = None
    if file.uploaded_by:
        primary_owner = BasicExpertInfo(
            email=file.uploaded_by,  # Using username as email since that's what we have
        )

    # group_id stays the same across versions, so a new version updates the
    # document instead of adding one.
    return Document(
        id=f"egnyte-{file.group_id}",
        sections=[TextSection(text=file_content_raw.strip(), link=web_url)],
        source=DocumentSource.EGNYTE,
        semantic_identifier=file_name,
        metadata=metadata,
        doc_updated_at=_parse_last_modified(file.last_modified),
        primary_owners=[primary_owner] if primary_owner else None,
    )


class EgnyteConnector(LoadConnector, PollConnector, OAuthConnector):
    supports_manual_credentials = True

    class AdditionalOauthKwargs(OAuthConnector.AdditionalOauthKwargs):
        egnyte_domain: str = Field(
            title="Egnyte Domain",
            description=(
                "The domain for the Egnyte instance (e.g. 'company' for company.egnyte.com)"
            ),
        )

    def __init__(
        self,
        folder_path: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.domain = ""  # will always be set in `load_credentials`
        # Egnyte paths start with "/", so "Shared/Docs" must match "/Shared/Docs".
        self.folder_path = "/" + (folder_path or "").strip("/")
        self.batch_size = batch_size
        self._ops: EgnyteSourceOperations | None = None

    @property
    def ops(self) -> EgnyteSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Egnyte")
        return self._ops

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.EGNYTE

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
        code_challenge: str | None = None,  # noqa: ARG003
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
        code_verifier: str | None = None,  # noqa: ARG003
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
        self._ops = EgnyteSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.EGNYTE.value, credentials
            )
        )
        return None

    def _get_files_list(self, path: str) -> Generator[EgnyteFile, None, None]:
        folder_paths = [path]
        while folder_paths:
            folder_path = folder_paths.pop()
            for page in self.ops.iterate_folder_pages(folder_path=folder_path):
                yield from page.files
                folder_paths.extend(folder.path for folder in page.folders)

    def _should_index_file(
        self,
        file: EgnyteFile,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> bool:
        """Return True if file should be included based on filters."""
        file_modified = _parse_last_modified(file.last_modified)
        if start_time and file_modified < start_time:
            return False
        if end_time and file_modified > end_time:
            return False

        return True

    def _process_files(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Generator[list[Document | HierarchyNode], None, None]:
        current_batch: list[Document | HierarchyNode] = []

        # Iterate through yielded files and filter them
        for file in self._get_files_list(self.folder_path):
            if not self._should_index_file(file, start_time, end_time):
                logger.debug("Skipping file '%s'.", file.path)
                continue

            try:
                content = self.ops.download_file(file_path=file.path)
            except EgnyteApiError as e:
                if e.status_code != 404:
                    raise
                logger.warning("File '%s' was deleted before download.", file.path)
                continue

            try:
                doc = _process_egnyte_file(
                    file=file,
                    file_content=io.BytesIO(content),
                    base_url=_EGNYTE_APP_BASE.format(domain=self.domain),
                    folder_path=self.folder_path,
                )
            except Exception:
                logger.exception("Failed to process file %s", file.path)
                continue

            if doc is not None:
                current_batch.append(doc)

                if len(current_batch) >= self.batch_size:
                    yield current_batch
                    current_batch = []

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
