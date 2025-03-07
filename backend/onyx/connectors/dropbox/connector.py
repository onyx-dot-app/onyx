from datetime import timezone
from io import BytesIO
from typing import Any

from dropbox import Dropbox  # type: ignore
from dropbox.exceptions import ApiError  # type:ignore
from dropbox.exceptions import AuthError  # type:ignore
from dropbox.files import FileMetadata  # type:ignore
from dropbox.files import FolderMetadata  # type:ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.exceptions import InsufficientPermissionsError
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


class DropboxConnector(LoadConnector, PollConnector):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.dropbox_client: Dropbox | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.dropbox_client = Dropbox(credentials["dropbox_access_token"])
        return None

    def _download_file(self, path: str) -> bytes:
        """Download a single file from Dropbox."""
        if self.dropbox_client is None:
            raise ConnectorMissingCredentialError("Dropbox")
        _, resp = self.dropbox_client.files_download(path)
        return resp.content

    def _get_shared_link(self, path: str) -> str:
        """Create a shared link for a file in Dropbox."""
        if self.dropbox_client is None:
            raise ConnectorMissingCredentialError("Dropbox")

        try:
            # Check if a shared link already exists
            shared_links = self.dropbox_client.sharing_list_shared_links(path=path)
            if shared_links.links:
                return shared_links.links[0].url

            link_metadata = (
                self.dropbox_client.sharing_create_shared_link_with_settings(path)
            )
            return link_metadata.url
        except ApiError as err:
            logger.exception(f"Failed to create a shared link for {path}: {err}")
            return ""

    def _yield_files_recursive(
        self,
        path: str,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> GenerateDocumentsOutput:
        """Yield files in batches from a specified Dropbox folder, including subfolders."""
        if self.dropbox_client is None:
            raise ConnectorMissingCredentialError("Dropbox")

        result = self.dropbox_client.files_list_folder(
            path,
            limit=self.batch_size,
            recursive=False,
            include_non_downloadable_files=False,
        )

        while True:
            batch: list[Document] = []
            for entry in result.entries:
                if isinstance(entry, FileMetadata):
                    modified_time = entry.client_modified
                    if modified_time.tzinfo is None:
                        # If no timezone info, assume it is UTC
                        modified_time = modified_time.replace(tzinfo=timezone.utc)
                    else:
                        # If not in UTC, translate it
                        modified_time = modified_time.astimezone(timezone.utc)

                    time_as_seconds = int(modified_time.timestamp())
                    if start and time_as_seconds < start:
                        continue
                    if end and time_as_seconds > end:
                        continue

                    downloaded_file = self._download_file(entry.path_display)
                    link = self._get_shared_link(entry.path_display)
                    try:
                        text = extract_file_text(
                            BytesIO(downloaded_file),
                            file_name=entry.name,
                            break_on_unprocessable=False,
                        )
                        batch.append(
                            Document(
                                id=f"doc:{entry.id}",
                                sections=[TextSection(link=link, text=text)],
                                source=DocumentSource.DROPBOX,
                                semantic_identifier=entry.name,
                                doc_updated_at=modified_time,
                                metadata={"type": "article"},
                            )
                        )
                    except Exception as e:
                        logger.exception(
                            f"Error decoding file {entry.path_display} as utf-8 error occurred: {e}"
                        )

                elif isinstance(entry, FolderMetadata):
                    yield from self._yield_files_recursive(entry.path_lower, start, end)

            if batch:
                yield batch

            if not result.has_more:
                break

            result = self.dropbox_client.files_list_folder_continue(result.cursor)

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        if self.dropbox_client is None:
            raise ConnectorMissingCredentialError("Dropbox")

        for batch in self._yield_files_recursive("", start, end):
            yield batch

        return None

    def validate_connector_settings(self) -> None:
        if self.dropbox_client is None:
            raise ConnectorMissingCredentialError("Dropbox credentials not loaded.")

        try:
            self.dropbox_client.files_list_folder(path="", limit=1)
        except AuthError as e:
            logger.exception("Failed to validate Dropbox credentials")
            raise CredentialInvalidError(f"Dropbox credential is invalid: {e.error}")
        except ApiError as e:
            if (
                e.error is not None
                and "insufficient_permissions" in str(e.error).lower()
            ):
                raise InsufficientPermissionsError(
                    "Your Dropbox token does not have sufficient permissions."
                )
            raise ConnectorValidationError(
                f"Unexpected Dropbox error during validation: {e.user_message_text or e}"
            )
        except Exception as e:
            raise Exception(f"Unexpected error during Dropbox settings validation: {e}")


if __name__ == "__main__":
    import os

    connector = DropboxConnector()
    connector.load_credentials(
        {
            "dropbox_access_token": os.environ["DROPBOX_ACCESS_TOKEN"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
