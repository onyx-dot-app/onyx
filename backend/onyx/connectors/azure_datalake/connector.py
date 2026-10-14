import os
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any
from typing import Optional
from urllib.parse import quote

from azure.core.exceptions import AzureError
from azure.core.exceptions import ClientAuthenticationError
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.storage.filedatalake import DataLakeServiceClient
from azure.storage.filedatalake import FileSystemClient

from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    process_onyx_metadata,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    extract_and_stage_tabular_file,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import is_tabular_file
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    tabular_file_to_sections,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger

logger = setup_logger()


class AzureDataLakeConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        container_name: str,
        path_prefix: str = "",
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.container_name = container_name.strip()
        self.path_prefix = (
            path_prefix.strip().lstrip("/")
            if path_prefix and path_prefix.strip()
            else ""
        )
        self.batch_size = batch_size
        self.service_client: Optional[DataLakeServiceClient] = None
        self.file_system_client: Optional[FileSystemClient] = None
        self.account_name: Optional[str] = None
        self._allow_images: bool | None = None
        self.size_threshold: int | None = BLOB_STORAGE_SIZE_THRESHOLD

    def set_allow_images(self, allow_images: bool) -> None:
        """Set whether to process images in this connector."""
        logger.info("Setting allow_images to %s for Azure Data Lake.", allow_images)
        self._allow_images = allow_images

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        authentication_method = credentials.get(
            "authentication_method", "account_key"
        )
        account_name = credentials.get("adls_access_key_id")
        if not account_name:
            raise ConnectorMissingCredentialError("Azure Storage Account Name")

        self.account_name = account_name.strip()
        account_url = f"https://{self.account_name}.dfs.core.windows.net"

        try:
            if authentication_method == "account_key":
                account_key = credentials.get("adls_secret_access_key")
                if not account_key:
                    raise ConnectorMissingCredentialError("Azure Storage Account Key")
                self.service_client = DataLakeServiceClient(
                    account_url=account_url,
                    credential=account_key.strip(),
                )
            elif authentication_method == "client_credentials":
                client_id = credentials.get("azure_client_id")
                client_secret = credentials.get("azure_client_secret")
                tenant_id = credentials.get("azure_tenant_id")
                if not all([client_id, client_secret, tenant_id]):
                    raise ConnectorMissingCredentialError(
                        "Azure Service Principal (Client ID, Client Secret, Tenant ID)"
                    )
                credential = ClientSecretCredential(
                    tenant_id=tenant_id.strip(),
                    client_id=client_id.strip(),
                    client_secret=client_secret.strip(),
                )
                self.service_client = DataLakeServiceClient(
                    account_url=account_url,
                    credential=credential,
                )
            else:
                raise ConnectorValidationError(
                    f"Unsupported authentication method: {authentication_method}"
                )

            self.file_system_client = self.service_client.get_file_system_client(
                self.container_name
            )
        except (ConnectorValidationError, ConnectorMissingCredentialError):
            raise
        except Exception as e:
            logger.exception("Failed to initialize Azure Data Lake client")
            raise UnexpectedValidationError(f"Azure Data Lake initialization error: {e}")

        return credentials

    def validate_connector_settings(self) -> None:
        if not self.file_system_client:
            raise ConnectorValidationError(
                "Azure Data Lake client is not initialized with credentials."
            )
        try:
            # Probe by listing up to 1 path in the file system/container
            paths = self.file_system_client.get_paths(
                path=self.path_prefix or None,
                recursive=False,
                max_results=1,
            )
            # Trigger evaluation of generator
            for _ in paths:
                break
        except ClientAuthenticationError as e:
            logger.exception("Azure Data Lake authentication failed during validation.")
            raise CredentialExpiredError(
                "Azure credentials failed authentication. Check your account name/key or service principal."
            ) from e
        except ResourceNotFoundError as e:
            logger.exception("Azure Data Lake container not found during validation.")
            raise ConnectorValidationError(
                f"Azure container '{self.container_name}' was not found in account '{self.account_name}'."
            ) from e
        except AzureError as e:
            logger.exception("Azure Data Lake validation error.")
            if "AuthorizationPermissionMismatch" in str(e) or "403" in str(e):
                raise InsufficientPermissionsError(
                    "Insufficient permissions to read Azure Data Lake container."
                ) from e
            raise UnexpectedValidationError(f"Azure Data Lake validation failed: {e}") from e

    def _build_web_url(self, file_path: str) -> str:
        encoded_path = quote(file_path)
        return (
            f"https://{self.account_name}.blob.core.windows.net/"
            f"{self.container_name}/{encoded_path}"
        )

    def _yield_datalake_files(
        self, start: datetime, end: datetime
    ) -> GenerateDocumentsOutput:
        if not self.file_system_client:
            raise ConnectorValidationError("Azure Data Lake client is not initialized.")

        batch: list[Document] = []
        try:
            paths = self.file_system_client.get_paths(
                path=self.path_prefix or None,
                recursive=True,
            )
        except Exception as e:
            logger.exception("Failed to retrieve paths from Azure Data Lake")
            raise UnexpectedValidationError(f"Failed to list Azure Data Lake paths: {e}") from e

        for path_item in paths:
            if path_item.is_directory:
                continue

            last_modified = path_item.last_modified
            if last_modified is None:
                last_modified = datetime.now(timezone.utc)
            elif last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)

            if not (start <= last_modified <= end):
                continue

            file_path = path_item.name
            file_name = os.path.basename(file_path)
            ext = get_file_ext(file_name)

            if ext not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
                logger.debug("Skipping unsupported file format: %s", file_path)
                continue

            file_size = path_item.content_length
            if (
                self.size_threshold is not None
                and file_size is not None
                and file_size > self.size_threshold
            ):
                logger.info(
                    "Skipping file %s because size %s exceeds threshold %s",
                    file_path,
                    file_size,
                    self.size_threshold,
                )
                continue

            link = self._build_web_url(file_path)

            try:
                file_client = self.file_system_client.get_file_client(file_path)
                download_stream = file_client.download_file()
                file_bytes = download_stream.readall()
            except Exception:
                logger.exception("Failed to download file %s from Azure Data Lake", file_path)
                continue

            # Handle tabular files
            if is_tabular_file(file_name):
                try:
                    if self.raw_file_callback:
                        result = extract_and_stage_tabular_file(
                            file=BytesIO(file_bytes),
                            file_name=file_name,
                            content_type="application/octet-stream",
                            raw_file_callback=self.raw_file_callback,
                            link=link,
                        )
                        tabular_sections = result.sections
                        staged_file_id = result.staged_file_id
                    else:
                        tabular_sections = tabular_file_to_sections(
                            BytesIO(file_bytes),
                            file_name=file_name,
                            link=link,
                        )
                        staged_file_id = None

                    batch.append(
                        Document(
                            id=f"azure_datalake:{self.container_name}:{file_path}",
                            sections=(
                                tabular_sections
                                if tabular_sections
                                else [TabularSection(link=link, text="")]
                            ),
                            source=DocumentSource.AZURE_DATALAKE,
                            semantic_identifier=file_name,
                            doc_updated_at=last_modified,
                            metadata={},
                            file_id=staged_file_id,
                        )
                    )
                    if len(batch) >= self.batch_size:
                        yield batch
                        batch = []
                except Exception:
                    logger.exception("Error processing tabular file %s", file_path)
                continue

            # Handle text, PDF, Word, Presentation documents
            try:
                extraction_result = extract_text_and_images(
                    BytesIO(file_bytes), file_name=file_name
                )
                onyx_metadata, custom_tags = process_onyx_metadata(
                    extraction_result.metadata
                )
                file_display_name = onyx_metadata.file_display_name or file_name
                time_updated = onyx_metadata.doc_updated_at or last_modified
                link = onyx_metadata.link or link
                primary_owners = onyx_metadata.primary_owners
                secondary_owners = onyx_metadata.secondary_owners

                sections: list[TextSection | ImageSection] = []
                if extraction_result.text_content.strip():
                    sections.append(
                        TextSection(
                            link=link,
                            text=extraction_result.text_content.strip(),
                        )
                    )

                if self._allow_images and extraction_result.embedded_images:
                    for img, img_name in extraction_result.embedded_images:
                        image_section, _ = store_image_and_create_section(
                            img,
                            file_path,
                            FileOrigin.CONNECTOR,
                        )
                        if image_section:
                            sections.append(image_section)

                batch.append(
                    Document(
                        id=f"azure_datalake:{self.container_name}:{file_path}",
                        sections=(
                            sections
                            if sections
                            else [TextSection(link=link, text="")]
                        ),
                        source=DocumentSource.AZURE_DATALAKE,
                        semantic_identifier=file_display_name,
                        doc_updated_at=time_updated,
                        metadata=custom_tags,
                        primary_owners=primary_owners,
                        secondary_owners=secondary_owners,
                    )
                )
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            except Exception:
                logger.exception("Error extracting text/images for %s", file_path)

        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        logger.debug("Loading all Azure Data Lake files")
        return self._yield_datalake_files(
            start=datetime(1970, 1, 1, tzinfo=timezone.utc),
            end=datetime.now(timezone.utc),
        )

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        logger.debug(
            "Polling Azure Data Lake files from %s to %s",
            start,
            end,
        )
        return self._yield_datalake_files(
            start=datetime.fromtimestamp(start, tz=timezone.utc),
            end=datetime.fromtimestamp(end, tz=timezone.utc),
        )
        

