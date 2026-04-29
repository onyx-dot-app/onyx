from __future__ import annotations

import json
import tempfile
import uuid
from io import BytesIO
from typing import Any
from typing import cast
from typing import IO
from typing import TYPE_CHECKING

import puremagic
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from google.cloud.storage import Client as GCSClient

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_current_tenant_if_none
from onyx.db.file_record import delete_filerecord_by_file_id
from onyx.db.file_record import get_filerecord_by_file_id
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.file_record import get_filerecord_by_prefix
from onyx.db.file_record import upsert_filerecord
from onyx.db.models import FileRecord
from onyx.file_store.file_store import FileStore
from onyx.file_store.s3_key_utils import generate_s3_key
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class GCSBackedFileStore(FileStore):
    """Google Cloud Storage backed file store with ADC/Workload Identity support."""

    def __init__(
        self,
        bucket_name: str,
        gcs_prefix: str | None = None,
        project_id: str | None = None,
        service_account_key_path: str | None = None,
        service_account_key_json: str | None = None,
    ) -> None:
        self._gcs_client: GCSClient | None = None
        self._bucket_name = bucket_name
        self._gcs_prefix = gcs_prefix or "onyx-files"
        self._project_id = project_id
        self._service_account_key_path = service_account_key_path
        self._service_account_key_json = service_account_key_json

    def _get_gcs_client(self) -> GCSClient:
        """Initialize GCS client if not already done.

        Authentication priority:
        1. Service account key file (GCS_SERVICE_ACCOUNT_KEY_PATH)
        2. Inline service account JSON (GCS_SERVICE_ACCOUNT_KEY_JSON)
        3. Application Default Credentials (Workload Identity, metadata server,
           gcloud CLI). Project ID is auto-resolved from the environment.
        """
        if self._gcs_client is None:
            try:
                from google.cloud import storage

                # Only pass project= when explicitly configured; otherwise let
                # the client auto-detect from credentials / metadata server.
                client_kwargs: dict[str, Any] = {}
                if self._project_id:
                    client_kwargs["project"] = self._project_id

                if self._service_account_key_path:
                    from google.oauth2 import service_account

                    credentials = service_account.Credentials.from_service_account_file(
                        self._service_account_key_path
                    )
                    self._gcs_client = storage.Client(
                        credentials=credentials, **client_kwargs
                    )
                elif self._service_account_key_json:
                    from google.oauth2 import service_account

                    info = json.loads(self._service_account_key_json)
                    credentials = service_account.Credentials.from_service_account_info(
                        info
                    )
                    # Fall back to the project_id embedded in the SA JSON
                    if "project" not in client_kwargs and info.get("project_id"):
                        client_kwargs["project"] = info["project_id"]
                    self._gcs_client = storage.Client(
                        credentials=credentials, **client_kwargs
                    )
                else:
                    # ADC: Workload Identity, metadata server, or gcloud CLI.
                    # Project ID is resolved from the environment automatically.
                    self._gcs_client = storage.Client(**client_kwargs)

            except ImportError as e:
                logger.error(f"Failed to import google-cloud-storage: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize GCS client: {e}")
                raise RuntimeError(f"Failed to initialize GCS client: {e}") from e

        return self._gcs_client

    def _get_object_key(self, file_name: str) -> str:
        """Generate object key from file name with tenant ID prefix.

        Reuses S3 key utilities — S3-safe keys are a strict subset of GCS-safe keys.
        """
        tenant_id = get_current_tenant_id()
        key = generate_s3_key(
            file_name=file_name,
            prefix=self._gcs_prefix,
            tenant_id=tenant_id,
            max_key_length=1024,
        )
        if len(key) == 1024:
            logger.info(f"File name was too long and was truncated: {file_name}")
        return key

    def initialize(self) -> None:
        """Initialize the GCS file store by ensuring the bucket exists."""
        from google.api_core.exceptions import Forbidden
        from google.api_core.exceptions import NotFound

        client = self._get_gcs_client()
        try:
            client.get_bucket(self._bucket_name)
            logger.info(f"GCS bucket '{self._bucket_name}' already exists")
        except NotFound:
            logger.info(f"Creating GCS bucket '{self._bucket_name}'")
            client.create_bucket(self._bucket_name)
            logger.info(f"Successfully created GCS bucket '{self._bucket_name}'")
        except Forbidden:
            logger.warning(
                f"GCS bucket '{self._bucket_name}' exists but access is forbidden"
            )
            raise RuntimeError(
                f"Access denied to GCS bucket '{self._bucket_name}'. Check permissions."
            )

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
        if file_id is None:
            file_id = str(uuid.uuid4())

        client = self._get_gcs_client()
        bucket = client.bucket(self._bucket_name)
        object_key = self._get_object_key(file_id)
        blob = bucket.blob(object_key)

        # Read content from IO object
        if hasattr(content, "read"):
            file_content = content.read()
            if hasattr(content, "seek"):
                content.seek(0)
        else:
            file_content = content

        blob.upload_from_string(file_content, content_type=file_type)

        try:
            with get_session_with_current_tenant_if_none(db_session) as db_session:
                upsert_filerecord(
                    file_id=file_id,
                    display_name=display_name or file_id,
                    file_origin=file_origin,
                    file_type=file_type,
                    bucket_name=self._bucket_name,
                    object_key=object_key,
                    db_session=db_session,
                    file_metadata=file_metadata,
                )
                db_session.commit()
        except Exception:
            try:
                blob.delete()
            except Exception:
                logger.warning(
                    f"Failed to clean up orphaned GCS blob {self._bucket_name}/{object_key} "
                    f"after DB persistence failure for file {file_id}",
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

        client = self._get_gcs_client()
        bucket = client.bucket(file_record.bucket_name)
        blob = bucket.blob(file_record.object_key)

        if use_tempfile:
            temp_file = tempfile.NamedTemporaryFile(mode="w+b", delete=True)
            blob.download_to_file(temp_file)
            temp_file.seek(0)
            return temp_file
        else:
            content = blob.download_as_bytes()
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
        """Get the size of a file in bytes by querying GCS blob metadata."""
        try:
            with get_session_with_current_tenant_if_none(db_session) as db_session:
                file_record = get_filerecord_by_file_id(
                    file_id=file_id, db_session=db_session
                )

            client = self._get_gcs_client()
            bucket = client.bucket(file_record.bucket_name)
            blob = bucket.blob(file_record.object_key)
            blob.reload()
            return blob.size
        except Exception as e:
            logger.warning(f"Error getting file size for {file_id}: {e}")
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
                        f"File record {file_id} with key {file_record.object_key} "
                        "has no bucket name, cannot delete from filestore"
                    )
                    delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
                    db_session.commit()
                    return

                from google.api_core.exceptions import NotFound

                client = self._get_gcs_client()
                bucket = client.bucket(file_record.bucket_name)
                blob = bucket.blob(file_record.object_key)
                try:
                    blob.delete()
                except NotFound:
                    logger.warning(
                        f"delete_file: File {file_id} not found in GCS "
                        f"(key: {file_record.object_key}), "
                        "cleaning up database record."
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
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            try:
                old_file_record = get_filerecord_by_file_id(
                    file_id=old_file_id, db_session=db_session
                )
                new_object_key = self._get_object_key(new_file_id)

                client = self._get_gcs_client()
                source_bucket = client.bucket(old_file_record.bucket_name)
                source_blob = source_bucket.blob(old_file_record.object_key)
                dest_bucket = client.bucket(self._bucket_name)

                source_bucket.copy_blob(source_blob, dest_bucket, new_object_key)

                file_metadata = cast(
                    dict[Any, Any] | None, old_file_record.file_metadata
                )

                upsert_filerecord(
                    file_id=new_file_id,
                    display_name=old_file_record.display_name,
                    file_origin=old_file_record.file_origin,
                    file_type=old_file_record.file_type,
                    bucket_name=self._bucket_name,
                    object_key=new_object_key,
                    db_session=db_session,
                    file_metadata=file_metadata,
                )

                delete_filerecord_by_file_id(file_id=old_file_id, db_session=db_session)

                db_session.commit()

                try:
                    source_blob.delete()
                except Exception:
                    logger.warning(
                        f"Failed to delete old GCS blob after changing file ID from "
                        f"{old_file_id} to {new_file_id}; blob may be orphaned",
                        exc_info=True,
                    )

            except Exception as e:
                db_session.rollback()
                logger.exception(
                    f"Failed to change file ID from {old_file_id} to {new_file_id}: {e}"
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
            return None

    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        """List all file IDs that start with the given prefix."""
        with get_session_with_current_tenant() as db_session:
            file_records = get_filerecord_by_prefix(
                prefix=prefix, db_session=db_session
            )
        return file_records
