from __future__ import annotations

import json
import tempfile
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from io import BytesIO
from typing import IO, TYPE_CHECKING, Any, cast

import puremagic
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from google.auth.credentials import Credentials as GoogleCredentials
    from google.cloud.storage import Client as GCSClient
    from google.oauth2.service_account import (
        Credentials as ServiceAccountCredentials,
    )

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_current_tenant_if_none,
)
from onyx.db.file_record import (
    delete_filerecord_by_file_id,
    get_filerecord_by_file_id,
    get_filerecord_by_file_id_for_update,
    get_filerecord_by_file_id_optional,
    get_filerecord_by_prefix,
    rename_filerecord,
    upsert_filerecord,
)
from onyx.db.models import FileRecord
from onyx.file_store.file_store import (
    PRESIGN_READ_CHUNK_BYTES,
    PresignableFileStore,
    PresignedUrlsNotSupportedError,
    content_byte_size,
    presign_expiry,
)
from onyx.file_store.models import (
    PendingPresignedUpload,
    PresignedRequest,
    StoredObjectStat,
)
from onyx.file_store.s3_key_utils import generate_s3_key
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _is_permission_denied(error: Exception) -> bool:
    # google-auth reports a failed signBlob call as TransportError with the
    # HTTP response in the message.
    message = str(error)
    return "403" in message or "PERMISSION_DENIED" in message


_SIGN_BLOB_HELP = (
    "GCS signed URLs without a key file sign through the IAM signBlob API. "
    "Grant roles/iam.serviceAccountTokenCreator on the service account to itself."
)


class GCSBackedFileStore(PresignableFileStore):
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
        # The credentials that sign URLs, owned here rather than read from the
        # client.
        self._signing_credentials: GoogleCredentials | None = None
        # Shared across threads, so the first operations build one client.
        self._client_lock = threading.Lock()
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
        with self._client_lock:
            if self._gcs_client is not None:
                return self._gcs_client
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
                logger.error("Failed to import google-cloud-storage: %s", e)
                raise
            except Exception as e:
                logger.error("Failed to initialize GCS client: %s", e)
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
            logger.info("File name was too long and was truncated: %s", file_name)
        return key

    def initialize(self) -> None:
        """Initialize the GCS file store by ensuring the bucket exists."""
        from google.api_core.exceptions import Forbidden, NotFound

        client = self._get_gcs_client()
        try:
            client.get_bucket(self._bucket_name)
            logger.info("GCS bucket '%s' already exists", self._bucket_name)
        except NotFound:
            logger.info("Creating GCS bucket '%s'", self._bucket_name)
            client.create_bucket(self._bucket_name)
            logger.info("Successfully created GCS bucket '%s'", self._bucket_name)
        except Forbidden:
            logger.warning(
                "GCS bucket '%s' exists but access is forbidden", self._bucket_name
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
                    file_size=content_byte_size(file_content),
                )
                db_session.commit()
        except Exception:
            # Clean up the uploaded blob unless a committed record still
            # references this exact object — on a failed overwrite the record
            # survives the rollback, so deleting the blob it points at would
            # turn the failed save into data loss. A record pointing at a
            # different bucket/key does not reference this upload, so the
            # blob is safe (and necessary) to remove.
            try:
                with get_session_with_current_tenant() as cleanup_session:
                    existing_record = get_filerecord_by_file_id_optional(
                        file_id=file_id, db_session=cleanup_session
                    )
                record_references_upload = (
                    existing_record is not None
                    and existing_record.bucket_name == self._bucket_name
                    and existing_record.object_key == object_key
                )
                if not record_references_upload:
                    blob.delete()
            except Exception:
                logger.warning(
                    "Failed to clean up orphaned GCS blob %s/%s "
                    "after DB persistence failure for file %s",
                    self._bucket_name,
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

            from google.api_core.exceptions import NotFound

            client = self._get_gcs_client()
            bucket = client.bucket(file_record.bucket_name)
            blob = bucket.blob(file_record.object_key)
            try:
                blob.reload()
            except NotFound as e:
                raise FileNotFoundError(
                    f"Object for file {file_id} does not exist"
                ) from e
            return blob.size
        except FileNotFoundError:
            raise
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
                # The lock makes a concurrent rename either finish first (the
                # record is then gone here) or wait until this delete commits.
                file_record = get_filerecord_by_file_id_for_update(
                    file_id=file_id, db_session=db_session
                )
                if file_record is None:
                    if error_on_missing:
                        raise RuntimeError(
                            f"File by id {file_id} does not exist or was deleted"
                        )
                    return
                delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
                if not file_record.bucket_name:
                    logger.error(
                        "File record %s with key %s "  # noqa: S608 - log message, not SQL
                        "has no bucket name, cannot delete from filestore",
                        file_id,
                        file_record.object_key,
                    )
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
                        "delete_file: File %s not found in GCS "
                        "(key: %s), cleaning up database record.",
                        file_id,
                        file_record.object_key,
                    )

                db_session.commit()

            except Exception:
                db_session.rollback()
                raise

    def change_file_id(
        self,
        old_file_id: str,
        new_file_id: str,
        db_session: Session | None = None,
    ) -> bool:
        """Rename a file by repointing its DB record at the existing blob.

        The blob is not moved — only file_id changes — and reads resolve via
        the stored object_key, so they still find it. The blob keeps its
        original key, so a file_id must not be reused for a new save_file after
        it has been renamed (the new write would overwrite the renamed blob).
        """
        if old_file_id == new_file_id:
            return True
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            try:
                renamed = rename_filerecord(old_file_id, new_file_id, db_session)
                db_session.commit()
                return renamed

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
            return None

    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        """List all file IDs that start with the given prefix."""
        with get_session_with_current_tenant() as db_session:
            file_records = get_filerecord_by_prefix(
                prefix=prefix, db_session=db_session
            )
        return file_records

    def _presign_bucket_name(self) -> str:
        return self._bucket_name

    def _presign_object_key(self, file_id: str) -> str:
        return self._get_object_key(file_id)

    def _service_account_key_credentials(
        self,
    ) -> ServiceAccountCredentials | None:
        """Credentials from the configured key file or inline JSON, if any."""
        from google.oauth2 import service_account

        if self._service_account_key_path:
            return service_account.Credentials.from_service_account_file(
                self._service_account_key_path
            )
        if self._service_account_key_json:
            return service_account.Credentials.from_service_account_info(
                json.loads(self._service_account_key_json)
            )
        return None

    def _get_signing_credentials(self) -> GoogleCredentials:
        """The key credentials when configured, else Application Default
        Credentials (Workload Identity or the metadata server)."""
        import google.auth

        with self._client_lock:
            if self._signing_credentials is None:
                key_credentials = self._service_account_key_credentials()
                if key_credentials is not None:
                    self._signing_credentials = key_credentials
                else:
                    self._signing_credentials, _ = google.auth.default(
                        scopes=[_CLOUD_PLATFORM_SCOPE]
                    )
            return self._signing_credentials

    def _iam_signer(self) -> tuple[str, str] | None:
        """(service account email, access token) for credentials without a
        key, which sign through IAM signBlob. None when they hold a key."""
        from google.auth import compute_engine
        from google.auth.credentials import Signing
        from google.auth.transport.requests import Request

        credentials = self._get_signing_credentials()
        if isinstance(credentials, Signing):
            return None
        # Workload Identity and the metadata server give these credentials.
        if not isinstance(credentials, compute_engine.Credentials):
            raise PresignedUrlsNotSupportedError(
                "GCS signed URLs need service account credentials, not "
                f"{type(credentials).__name__}"
            )
        # A refresh also replaces the "default" email with the real one. A
        # failed refresh is a metadata server problem, so it is raised as is.
        if not credentials.valid:
            credentials.refresh(Request())
        if credentials.token is None:
            raise PresignedUrlsNotSupportedError("GCS credentials have no token")
        return credentials.service_account_email, credentials.token

    def _signed_url(
        self,
        bucket_name: str,
        object_key: str,
        method: str,
        ttl_seconds: int,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        from google.auth.exceptions import GoogleAuthError

        blob = self._get_gcs_client().bucket(bucket_name).blob(object_key)
        signer = self._iam_signer()
        try:
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=ttl_seconds),
                method=method,
                content_type=content_type,
                # The library adds headers to the dict it gets.
                headers=dict(headers) if headers is not None else None,
                service_account_email=signer[0] if signer else None,
                access_token=signer[1] if signer else None,
            )
        except GoogleAuthError as e:
            # Only a denied signBlob means the identity cannot sign. Other
            # errors (network, IAM outage) are raised as they are.
            if _is_permission_denied(e):
                raise PresignedUrlsNotSupportedError(f"{_SIGN_BLOB_HELP} ({e})") from e
            raise

    def _sign_download(
        self, bucket_name: str, object_key: str, ttl_seconds: int
    ) -> PresignedRequest:
        expires_at = presign_expiry(ttl_seconds)
        url = self._signed_url(bucket_name, object_key, "GET", ttl_seconds)
        return PresignedRequest(
            url=url, method="GET", headers={}, expires_at=expires_at
        )

    def _sign_upload(
        self, pending: PendingPresignedUpload, ttl_seconds: int
    ) -> PresignedRequest:
        # GCS cannot check a SHA-256, so finalize hashes the object. The
        # generation match lets the URL create the object only once.
        headers = {
            "x-goog-if-generation-match": "0",
            "x-goog-content-length-range": f"{pending.size},{pending.size}",
        }
        expires_at = presign_expiry(ttl_seconds)
        url = self._signed_url(
            pending.bucket_name,
            pending.object_key,
            "PUT",
            ttl_seconds,
            content_type=pending.file_type,
            headers=headers,
        )
        return PresignedRequest(
            url=url,
            method="PUT",
            headers={"Content-Type": pending.file_type, **headers},
            expires_at=expires_at,
        )

    def _stat_object(
        self, bucket_name: str, object_key: str
    ) -> StoredObjectStat | None:
        blob = self._get_gcs_client().bucket(bucket_name).get_blob(object_key)
        if blob is None or blob.size is None:
            return None
        return StoredObjectStat(size=blob.size, sha256=None)

    def _read_object_chunks(self, bucket_name: str, object_key: str) -> Iterator[bytes]:
        blob = self._get_gcs_client().bucket(bucket_name).blob(object_key)
        with blob.open("rb", chunk_size=PRESIGN_READ_CHUNK_BYTES) as reader:
            while chunk := reader.read(PRESIGN_READ_CHUNK_BYTES):
                yield chunk

    def _delete_object(self, bucket_name: str, object_key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self._get_gcs_client().bucket(bucket_name).blob(object_key).delete()
        except NotFound:
            pass
