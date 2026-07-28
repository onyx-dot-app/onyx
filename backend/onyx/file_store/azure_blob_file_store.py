from __future__ import annotations

import tempfile
import uuid
from io import BytesIO
from typing import IO, TYPE_CHECKING, Any, cast

import puremagic
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from azure.storage.blob import BlobServiceClient

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_current_tenant_if_none,
)
from onyx.db.file_record import (
    delete_filerecord_by_file_id,
    get_filerecord_by_file_id,
    get_filerecord_by_file_id_optional,
    get_filerecord_by_prefix,
    upsert_filerecord,
)
from onyx.db.models import FileRecord
from onyx.file_store.file_store import FileStore
from onyx.file_store.s3_key_utils import generate_s3_key
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class AzureBlobBackedFileStore(FileStore):
    """Azure Blob Storage backed file store with Workload Identity support.

    The container name maps to the generic `bucket_name` column of `file_record`.
    """

    def __init__(
        self,
        container_name: str,
        azure_prefix: str | None = None,
        account_name: str | None = None,
        account_url: str | None = None,
        connection_string: str | None = None,
        account_key: str | None = None,
    ) -> None:
        self._blob_service_client: BlobServiceClient | None = None
        self._container_name = container_name
        self._azure_prefix = azure_prefix or "onyx-files"
        self._connection_string = connection_string

        # Validate auth config eagerly so misconfiguration fails at
        # construction (i.e. during startup initialize()) rather than on the
        # first read/write. A connection string needs neither URL nor key.
        self._account_url: str | None = None
        self._account_key_credential: dict[str, str] | None = None
        if not connection_string:
            if account_url:
                self._account_url = account_url
            elif account_name:
                self._account_url = f"https://{account_name}.blob.core.windows.net"
            else:
                raise RuntimeError(
                    "Azure file store requires AZURE_STORAGE_ACCOUNT_URL or "
                    "AZURE_STORAGE_ACCOUNT_NAME (unless "
                    "AZURE_STORAGE_CONNECTION_STRING is set)"
                )
            if account_key:
                if not account_name:
                    raise RuntimeError(
                        "AZURE_STORAGE_ACCOUNT_NAME is required when "
                        "authenticating with AZURE_STORAGE_ACCOUNT_KEY"
                    )
                self._account_key_credential = {
                    "account_name": account_name,
                    "account_key": account_key,
                }

    def _get_blob_service_client(self) -> BlobServiceClient:
        """Initialize the Azure Blob service client if not already done.

        Authentication priority:
        1. Connection string (AZURE_STORAGE_CONNECTION_STRING)
        2. Account key (AZURE_STORAGE_ACCOUNT_KEY)
        3. DefaultAzureCredential — AKS Workload Identity, managed identity,
           environment credentials, or local `az login`.
        """
        if self._blob_service_client is None:
            try:
                from azure.storage.blob import BlobServiceClient

                if self._connection_string:
                    self._blob_service_client = (
                        BlobServiceClient.from_connection_string(
                            self._connection_string
                        )
                    )
                elif self._account_url is None:
                    # Unreachable: __init__ resolves the URL for every auth
                    # mode except connection string.
                    raise RuntimeError("Azure account URL was not resolved")
                elif self._account_key_credential is not None:
                    self._blob_service_client = BlobServiceClient(
                        account_url=self._account_url,
                        credential=self._account_key_credential,
                    )
                else:
                    from azure.identity import DefaultAzureCredential

                    self._blob_service_client = BlobServiceClient(
                        account_url=self._account_url,
                        credential=DefaultAzureCredential(),
                    )

            except ImportError as e:
                logger.error("Failed to import azure-storage-blob: %s", e)
                raise
            except Exception as e:
                logger.error("Failed to initialize Azure Blob client: %s", e)
                raise RuntimeError(
                    f"Failed to initialize Azure Blob client: {e}"
                ) from e

        return self._blob_service_client

    def _get_object_key(self, file_name: str) -> str:
        """Generate blob name from file name with tenant ID prefix.

        Reuses S3 key utilities — S3-safe keys are a strict subset of valid
        Azure blob names (both allow `/` path segments and cap at 1024 chars).
        """
        tenant_id = get_current_tenant_id()
        key = generate_s3_key(
            file_name=file_name,
            prefix=self._azure_prefix,
            tenant_id=tenant_id,
            max_key_length=1024,
        )
        if len(key) == 1024:
            logger.info("File name was too long and was truncated: %s", file_name)
        return key

    def initialize(self) -> None:
        """Initialize the Azure file store by ensuring the container exists."""
        from azure.core.exceptions import HttpResponseError, ResourceExistsError

        client = self._get_blob_service_client()
        container_client = client.get_container_client(self._container_name)
        try:
            if container_client.exists():
                logger.info("Azure container '%s' already exists", self._container_name)
                return
            logger.info("Creating Azure container '%s'", self._container_name)
            container_client.create_container()
            logger.info(
                "Successfully created Azure container '%s'", self._container_name
            )
        except ResourceExistsError:
            # exists() said no just above, so someone else created the
            # container in between — benign, but surprising enough to flag.
            logger.warning(
                "Azure container '%s' was created concurrently after a negative "
                "existence check",
                self._container_name,
            )
        except HttpResponseError as e:
            if e.status_code == 403:
                logger.warning(
                    "Azure container '%s' exists but access is forbidden",
                    self._container_name,
                )
                raise RuntimeError(
                    f"Access denied to Azure container '{self._container_name}'. "
                    "Check permissions."
                ) from e
            raise

    def has_file(
        self,
        file_id: str,
        file_origin: FileOrigin,
        file_type: str,
        db_session: Session | None = None,
    ) -> bool:
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            file_record = get_filerecord_by_file_id_optional(
                file_id=file_id, db_session=db_session
            )
        return (
            file_record is not None
            and file_record.file_origin == file_origin
            and file_record.file_type == file_type
        )

    def save_file(
        self,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
        file_id: str | None = None,
        db_session: Session | None = None,
    ) -> str:
        from azure.storage.blob import ContentSettings

        if file_id is None:
            file_id = str(uuid.uuid4())

        client = self._get_blob_service_client()
        object_key = self._get_object_key(file_id)
        blob_client = client.get_blob_client(
            container=self._container_name, blob=object_key
        )

        # Read content from IO object
        if hasattr(content, "read"):
            file_content = content.read()
            if hasattr(content, "seek"):
                content.seek(0)
        else:
            file_content = content

        blob_client.upload_blob(
            file_content,
            overwrite=True,
            content_settings=ContentSettings(content_type=file_type),
        )

        try:
            with get_session_with_current_tenant_if_none(db_session) as db_session:
                upsert_filerecord(
                    file_id=file_id,
                    display_name=display_name or file_id,
                    file_origin=file_origin,
                    file_type=file_type,
                    bucket_name=self._container_name,
                    object_key=object_key,
                    db_session=db_session,
                    file_metadata=file_metadata,
                )
                db_session.commit()
        except Exception:
            # Clean up the uploaded blob only when this save was creating a
            # brand-new file. On an overwrite of an existing file_id the
            # committed record still references this key after rollback, so
            # deleting the blob would turn a failed overwrite into data loss.
            try:
                with get_session_with_current_tenant() as cleanup_session:
                    existing_record = get_filerecord_by_file_id_optional(
                        file_id=file_id, db_session=cleanup_session
                    )
                if existing_record is None:
                    blob_client.delete_blob()
            except Exception:
                logger.warning(
                    "Failed to clean up orphaned Azure blob %s/%s "
                    "after DB persistence failure for file %s",
                    self._container_name,
                    object_key,
                    file_id,
                    exc_info=True,
                )
            raise

        return file_id

    def read_file(
        self,
        file_id: str,
        mode: str | None = None,  # noqa: ARG002
        use_tempfile: bool = False,
        db_session: Session | None = None,
    ) -> IO[bytes]:
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            file_record = get_filerecord_by_file_id(
                file_id=file_id, db_session=db_session
            )

        client = self._get_blob_service_client()
        blob_client = client.get_blob_client(
            container=file_record.bucket_name, blob=file_record.object_key
        )

        if use_tempfile:
            temp_file = tempfile.NamedTemporaryFile(mode="w+b", delete=True)
            blob_client.download_blob().readinto(temp_file)
            temp_file.seek(0)
            return temp_file
        else:
            # No encoding is set on download_blob(), so readall() returns bytes.
            content = cast(bytes, blob_client.download_blob().readall())
            return BytesIO(content)

    def read_file_record(
        self, file_id: str, db_session: Session | None = None
    ) -> FileRecord:
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            file_record = get_filerecord_by_file_id(
                file_id=file_id, db_session=db_session
            )
        return file_record

    def get_file_size(
        self, file_id: str, db_session: Session | None = None
    ) -> int | None:
        """Get the size of a file in bytes by querying Azure blob properties."""
        try:
            with get_session_with_current_tenant_if_none(db_session) as db_session:
                file_record = get_filerecord_by_file_id(
                    file_id=file_id, db_session=db_session
                )

            client = self._get_blob_service_client()
            blob_client = client.get_blob_client(
                container=file_record.bucket_name, blob=file_record.object_key
            )
            properties = blob_client.get_blob_properties()
            return properties.size
        except Exception as e:
            logger.warning("Error getting file size for %s: %s", file_id, e)
            return None

    def delete_file(
        self,
        file_id: str,
        error_on_missing: bool = True,
        db_session: Session | None = None,
    ) -> None:
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            try:
                file_record = get_filerecord_by_file_id_optional(
                    file_id=file_id, db_session=db_session
                )
                if file_record is None:
                    if error_on_missing:
                        raise RuntimeError(
                            f"File by id {file_id} does not exist or was deleted"
                        )
                    return
                if not file_record.bucket_name:
                    logger.error(
                        "File record %s with key %s "  # noqa: S608 - log message, not SQL
                        "has no bucket name, cannot delete from filestore",
                        file_id,
                        file_record.object_key,
                    )
                    delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
                    db_session.commit()
                    return

                from azure.core.exceptions import ResourceNotFoundError

                client = self._get_blob_service_client()
                blob_client = client.get_blob_client(
                    container=file_record.bucket_name, blob=file_record.object_key
                )
                try:
                    blob_client.delete_blob()
                except ResourceNotFoundError as e:
                    # Tolerate only a missing blob. A missing container means
                    # storage is misconfigured or unavailable — keep the DB
                    # record so the file is still resolvable once fixed.
                    # (error_code is set at runtime but absent from the
                    # azure-core stubs, hence getattr.)
                    if getattr(e, "error_code", None) != "BlobNotFound":
                        raise
                    logger.warning(
                        "delete_file: File %s not found in Azure Blob Storage "
                        "(key: %s), cleaning up database record.",
                        file_id,
                        file_record.object_key,
                    )

                delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
                db_session.commit()

            except Exception:
                db_session.rollback()
                raise

    def change_file_id(
        self,
        old_file_id: str,
        new_file_id: str,
        db_session: Session | None = None,
    ) -> None:
        """Rename a file by repointing its DB record at the existing blob.

        The blob is not moved — only file_id changes — and reads resolve via
        the stored object_key, so they still find it. The blob keeps its
        original key, so a file_id must not be reused for a new save_file after
        it has been renamed (the new write would overwrite the renamed blob).
        """
        if old_file_id == new_file_id:
            return
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            try:
                old_file_record = get_filerecord_by_file_id(
                    file_id=old_file_id, db_session=db_session
                )
                file_metadata = cast(
                    dict[Any, Any] | None, old_file_record.file_metadata
                )

                # Reuse the old record's bucket/object_key — the blob stays put.
                upsert_filerecord(
                    file_id=new_file_id,
                    display_name=old_file_record.display_name,
                    file_origin=old_file_record.file_origin,
                    file_type=old_file_record.file_type,
                    bucket_name=old_file_record.bucket_name,
                    object_key=old_file_record.object_key,
                    db_session=db_session,
                    file_metadata=file_metadata,
                )

                delete_filerecord_by_file_id(file_id=old_file_id, db_session=db_session)

                db_session.commit()

            except Exception as e:
                db_session.rollback()
                logger.exception(
                    "Failed to change file ID from %s to %s: %s",
                    old_file_id,
                    new_file_id,
                    e,
                )
                raise

    def get_file_with_mime_type(self, file_id: str) -> FileWithMimeType | None:
        mime_type: str = "application/octet-stream"
        try:
            file_io = self.read_file(file_id, mode="b")
            file_content = file_io.read()
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)
            return FileWithMimeType(data=file_content, mime_type=mime_type)
        except Exception:
            logger.warning(
                "Failed to read file %s from Azure Blob Storage",
                file_id,
                exc_info=True,
            )
            return None

    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        """List all file IDs that start with the given prefix."""
        with get_session_with_current_tenant() as db_session:
            file_records = get_filerecord_by_prefix(
                prefix=prefix, db_session=db_session
            )
        return file_records
