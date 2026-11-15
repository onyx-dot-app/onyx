import base64
import hashlib
import re
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial, reduce
from io import BytesIO
from typing import IO, TYPE_CHECKING, Any, NotRequired, TypedDict, TypeVar, cast

import puremagic
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    FILE_STORE_PRESIGN_DEFAULT_TTL_SECONDS,
    FILE_STORE_PRESIGN_MAX_TTL_SECONDS,
    FILE_STORE_PRESIGN_MAX_UPLOAD_BYTES,
    S3_AWS_ACCESS_KEY_ID,
    S3_AWS_SECRET_ACCESS_KEY,
    S3_ENDPOINT_URL,
    S3_FILE_STORE_BUCKET_NAME,
    S3_FILE_STORE_PREFIX,
    S3_GENERATE_LOCAL_CHECKSUM,
    S3_LEGACY_AWS_ACCESS_KEY_ID,
    S3_LEGACY_AWS_SECRET_ACCESS_KEY,
    S3_LEGACY_ENDPOINT_URL,
    S3_VERIFY_SSL,
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
from onyx.db.models import FileRecord as FileStoreModel
from onyx.file_store.models import (
    PendingPresignedUpload,
    PresignedRequest,
    PresignedUpload,
    StoredObjectStat,
)
from onyx.file_store.s3_key_utils import generate_s3_key
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.literals import BucketLocationConstraintType
    from mypy_boto3_s3.type_defs import BlobTypeDef

    from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore
    from onyx.file_store.gcs_file_store import GCSBackedFileStore

logger = setup_logger()


# Persisted in file_record.file_size when the backing object is confirmed
# missing, so listings stop re-probing the object store for it. Rendered as
# "unknown" (None) in API responses.
FILE_SIZE_MISSING_SENTINEL = -1


def content_byte_size(file_content: object) -> int | None:
    """Stored size in bytes of save_file content. str content is uploaded
    UTF-8 encoded by every backend, so its size is the encoded length."""
    if isinstance(file_content, (bytes, bytearray)):
        return len(file_content)
    if isinstance(file_content, str):
        return len(file_content.encode("utf-8"))
    return None


_T = TypeVar("_T")


class PresignedUrlsNotSupportedError(Exception):
    """The credentials of a cloud store cannot sign URLs, or the file is not
    reachable through a URL (for example, only in the legacy MinIO store)."""


class PresignedUploadNotFoundError(Exception):
    """The pending upload is unknown, already finalized, or expired."""


class PresignedUploadInProgressError(Exception):
    """Another call is finalizing the same pending upload."""


class PresignedUploadVerificationError(Exception):
    """The uploaded object is missing or does not match the size and SHA-256
    given to presign_upload."""


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
PRESIGN_READ_CHUNK_BYTES = 8 * 1024 * 1024
# How long after its URL expires a presigned upload can still be finalized.
_PENDING_UPLOAD_GRACE_SECONDS = 5 * 60


def presign_ttl_seconds(ttl: timedelta | None) -> int:
    if ttl is None:
        return FILE_STORE_PRESIGN_DEFAULT_TTL_SECONDS
    seconds = int(ttl.total_seconds())
    if not 0 < seconds <= FILE_STORE_PRESIGN_MAX_TTL_SECONDS:
        raise ValueError(
            f"A presigned URL TTL must be 1 to {FILE_STORE_PRESIGN_MAX_TTL_SECONDS} seconds"
        )
    return seconds


def presign_expiry(ttl_seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=ttl_seconds)


def _pending_upload_cache_key(pending_upload_id: str) -> str:
    return f"file_store_presigned_upload:{pending_upload_id}"


def pending_upload_lock_name(pending_upload_id: str) -> str:
    return f"file_store_presigned_upload_finalize:{pending_upload_id}"


# Covers hashing the largest allowed object on stores that keep no SHA-256.
# A Redis lock expires after this; the Postgres cache backend's advisory lock
# holds its connection until finalize ends.
_FINALIZE_LOCK_TIMEOUT_SECONDS = 30 * 60


class S3PutKwargs(TypedDict):
    ChecksumSHA256: NotRequired[str]


# Marks legacy objects this release writes. The object store already holds that
# version or a newer one, so a later copy of MinIO into the object store must
# never let a marked object replace an app write.
DUAL_WRITE_METADATA_KEY = "onyx-dual-write"


def s3_error_code(e: ClientError) -> str | None:
    return e.response.get("Error", {}).get("Code")


def is_missing_object(e: ClientError) -> bool:
    return s3_error_code(e) in ("404", "NoSuchKey", "NotFound")


# A failed legacy write leaves a marker at this prefix plus the key in the
# object store, for a later copy of MinIO to replay the write into MinIO.
LEGACY_OUT_OF_SYNC_PREFIX = "onyx-legacy-out-of-sync/"


# Retiring MinIO writes this object once MinIO holds nothing the object store
# lacks, so running processes stop writing to MinIO without a restart.
LEGACY_RETIRED_MARKER_KEY = "onyx-legacy-minio-retired"
LEGACY_RETIRED_RECHECK_SECONDS = 60
# Module level because a store is built per request. Two threads that check at
# once both HEAD the marker, which is harmless, so the dict is unguarded.
_legacy_retired: dict[tuple[str, str], tuple[float, bool]] = {}


def legacy_store_retired(client: "S3Client", bucket: str) -> bool:
    """Whether the retire marker is in the bucket, checked at most once a
    minute per store. A failed check keeps the last answer."""
    store = (client.meta.endpoint_url, bucket)
    checked_at, retired = _legacy_retired.get(store, (float("-inf"), False))
    now = time.monotonic()
    if now - checked_at < LEGACY_RETIRED_RECHECK_SECONDS:
        return retired
    try:
        client.head_object(Bucket=bucket, Key=LEGACY_RETIRED_MARKER_KEY)
        retired = True
    except Exception as e:
        if isinstance(e, ClientError) and is_missing_object(e):
            retired = False
        else:
            logger.warning(
                "Could not check whether the legacy MinIO store is retired",
                exc_info=True,
            )
    _legacy_retired[store] = (now, retired)
    return retired


def build_s3_client(
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    region_name: str,
    verify_ssl: bool,
    fail_fast: bool = False,
    max_pool_connections: int | None = None,
    signs_urls: bool = False,
) -> "S3Client":
    try:
        # Imported here: boto3 costs ~16 MB and most workers never build an S3 client.
        import boto3
        from botocore.config import Config

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": region_name,
        }
        # AWS keeps boto3's defaults, so a Config is passed only when one applies.
        configs: list[Config] = []
        # One connection per concurrent caller, or the pool opens and drops a
        # connection for every request beyond boto3's default of ten.
        if max_pool_connections is not None:
            configs.append(Config(max_pool_connections=max_pool_connections))
        # An endpoint URL means a self-hosted store, which needs path-style addressing.
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
            configs.append(
                Config(signature_version="s3v4", s3={"addressing_style": "path"})
            )
            # A hung secondary store must not hold up the request it serves.
            if fail_fast:
                configs.append(
                    Config(
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"total_max_attempts": 2},
                    )
                )
            if not verify_ssl:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                client_kwargs["verify"] = False
        # On AWS a signed URL needs SigV4, which also signs its headers, and a
        # regional host, since the global host can redirect a PUT.
        elif signs_urls:
            configs.append(
                Config(signature_version="s3v4", s3={"addressing_style": "virtual"})
            )
        if configs:
            client_kwargs["config"] = reduce(Config.merge, configs)

        # Without explicit keys, boto3 uses the IAM role or default credentials.
        if access_key_id and secret_access_key:
            client_kwargs.update(
                {
                    "aws_access_key_id": access_key_id,
                    "aws_secret_access_key": secret_access_key,
                }
            )
        return boto3.client(**client_kwargs)

    except Exception as e:
        logger.error("Failed to initialize S3 client: %s", e)
        raise RuntimeError(f"Failed to initialize S3 client: {e}") from e


def ensure_bucket(s3_client: "S3Client", bucket_name: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info("S3 bucket '%s' already exists", bucket_name)
        return
    except ClientError as e:
        error_code = s3_error_code(e)
        if error_code == "403":
            logger.warning("S3 bucket '%s' exists but access is forbidden", bucket_name)
            raise RuntimeError(
                f"Access denied to S3 bucket '{bucket_name}'. Check credentials and permissions."
            ) from e
        if error_code != "404":
            logger.error("Failed to check S3 bucket '%s': %s", bucket_name, e)
            raise RuntimeError(f"Failed to check S3 bucket '{bucket_name}': {e}") from e

    logger.info("Creating S3 bucket '%s'", bucket_name)
    region = s3_client.meta.region_name
    # AWS needs a LocationConstraint outside us-east-1.
    if region and region != "us-east-1":
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                # The stub wants the region Literal, and meta.region_name is a str.
                "LocationConstraint": cast("BucketLocationConstraintType", region)
            },
        )
    else:
        s3_client.create_bucket(Bucket=bucket_name)
    logger.info("Successfully created S3 bucket '%s'", bucket_name)


class FileStore(ABC):
    """
    An abstraction for storing files and large binary objects.
    """

    @abstractmethod
    def initialize(self) -> None:
        """
        Should generally be called once before any other methods are called.
        """
        raise NotImplementedError

    @abstractmethod
    def has_file(
        self,
        file_id: str,
        file_origin: FileOrigin,
        file_type: str,
    ) -> bool:
        """
        Check if a file record with the given origin and type exists.

        Note: implementations check the metadata record in the database, not
        the backing blob itself — content is assumed present when the record
        exists.

        Parameters:
        - file_id: Unique ID of the file to check for
        - file_origin: Origin of the file
        - file_type: Type of the file
        """
        raise NotImplementedError

    @abstractmethod
    def save_file(
        self,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
        file_id: str | None = None,
    ) -> str:
        """
        Save a file to the blob store

        Parameters:
        - content: Contents of the file
        - display_name: Display name of the file to save
        - file_origin: Origin of the file
        - file_type: Type of the file
        - file_metadata: Additional metadata for the file
        - file_id: Unique ID of the file to save. If not provided, a random UUID will be generated.
                   It is generally NOT recommended to provide this.

        Returns:
            The unique ID of the file that was saved.
        """
        raise NotImplementedError

    @abstractmethod
    def read_file(
        self, file_id: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        """
        Read the content of a given file by the ID

        Parameters:
        - file_id: Unique ID of file to read
        - mode: Mode to open the file (e.g. 'b' for binary)
        - use_tempfile: Whether to use a temporary file to store the contents
                        in order to avoid loading the entire file into memory

        Returns:
            Contents of the file and metadata dict
        """

    @abstractmethod
    def read_file_record(self, file_id: str) -> FileStoreModel:
        """
        Read the file record by the ID
        """

    @abstractmethod
    def get_file_size(
        self, file_id: str, db_session: Session | None = None
    ) -> int | None:
        """
        Get the size of a file in bytes.
        Optionally provide a db_session for database access.
        """

    @abstractmethod
    def delete_file(self, file_id: str, error_on_missing: bool = True) -> None:
        """
        Delete a file by its ID.

        Parameters:
        - file_id: ID of file to delete
        - error_on_missing: If False, silently return when the file record
          does not exist instead of raising.
        """

    @abstractmethod
    def get_file_with_mime_type(self, file_id: str) -> FileWithMimeType | None:
        """
        Get the file + parse out the mime type.
        """

    @abstractmethod
    def change_file_id(self, old_file_id: str, new_file_id: str) -> bool:
        """
        Change the file ID of an existing file.

        Parameters:
        - old_file_id: Current file ID
        - new_file_id: New file ID to assign

        Returns False when the file does not exist, e.g. a concurrent delete won.
        """
        raise NotImplementedError

    @abstractmethod
    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        """
        List all file IDs that start with the given prefix.
        """


class PresignableFileStore(FileStore):
    """A file store on a cloud object store (S3, GCS, Azure) that can sign URLs.
    Callers check isinstance(store, PresignableFileStore); other stores have no
    presigned URLs. The hooks take the bucket, so a store for another bucket can
    reuse the signer."""

    # The largest object one presigned PUT can write.
    _presign_max_upload_bytes = FILE_STORE_PRESIGN_MAX_UPLOAD_BYTES

    @abstractmethod
    def _presign_bucket_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _presign_object_key(self, file_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def _sign_download(
        self, bucket_name: str, object_key: str, ttl_seconds: int
    ) -> PresignedRequest:
        raise NotImplementedError

    @abstractmethod
    def _sign_upload(
        self, pending: PendingPresignedUpload, ttl_seconds: int
    ) -> PresignedRequest:
        """The URL must not let the client replace a finalized object with
        other content."""
        raise NotImplementedError

    @abstractmethod
    def _stat_object(
        self, bucket_name: str, object_key: str
    ) -> StoredObjectStat | None:
        """None when the object does not exist."""
        raise NotImplementedError

    @abstractmethod
    def _read_object_chunks(self, bucket_name: str, object_key: str) -> Iterator[bytes]:
        raise NotImplementedError

    @abstractmethod
    def _delete_object(self, bucket_name: str, object_key: str) -> None:
        """Does nothing when the object does not exist."""
        raise NotImplementedError

    def _on_presigned_upload_finalized(self, bucket_name: str, object_key: str) -> None:
        """Runs after the file_record row of a presigned upload is committed."""

    def presign_download(
        self,
        file_id: str,
        ttl: timedelta | None = None,
        db_session: Session | None = None,
    ) -> PresignedRequest:
        """A GET URL for the object of an existing file record."""
        ttl_seconds = presign_ttl_seconds(ttl)
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            file_record = get_filerecord_by_file_id(
                file_id=file_id, db_session=db_session
            )
        return self._sign_download(
            file_record.bucket_name, file_record.object_key, ttl_seconds
        )

    def presign_upload(
        self,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        size: int,
        sha256: str,
        ttl: timedelta | None = None,
    ) -> PresignedUpload:
        """A PUT URL for a new object. Reserves a file ID and object key, but
        writes no file_record row until finalize_presigned_upload. sha256 is
        the hex digest of the content to upload."""
        ttl_seconds = presign_ttl_seconds(ttl)
        if not 0 <= size <= self._presign_max_upload_bytes:
            raise ValueError(
                f"A presigned upload size must be 0 to {self._presign_max_upload_bytes} bytes"
            )
        sha256 = sha256.lower()
        if not _SHA256_HEX.fullmatch(sha256):
            raise ValueError("sha256 must be a hex SHA-256 digest")

        file_id = str(uuid.uuid4())
        pending = PendingPresignedUpload(
            file_id=file_id,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            bucket_name=self._presign_bucket_name(),
            object_key=self._presign_object_key(file_id),
            size=size,
            sha256=sha256,
        )
        request = self._sign_upload(pending, ttl_seconds)
        pending_upload_id = uuid.uuid4().hex
        get_cache_backend().set(
            _pending_upload_cache_key(pending_upload_id),
            pending.model_dump_json(),
            ex=ttl_seconds + _PENDING_UPLOAD_GRACE_SECONDS,
        )
        return PresignedUpload(
            pending_upload_id=pending_upload_id, file_id=file_id, request=request
        )

    def finalize_presigned_upload(
        self, pending_upload_id: str, db_session: Session | None = None
    ) -> str:
        """Checks the size and SHA-256 of the uploaded object, then writes its
        file_record row. On a mismatch, deletes the object and raises
        PresignedUploadVerificationError. Returns the file ID.

        Finalize calls for one pending upload run one at a time, so a late
        second call cannot recreate a record that was deleted after the first.
        """
        cache = get_cache_backend()
        lock = cache.lock(
            pending_upload_lock_name(pending_upload_id),
            timeout=_FINALIZE_LOCK_TIMEOUT_SECONDS,
        )
        if not lock.acquire(blocking=False):
            raise PresignedUploadInProgressError(
                f"Pending upload {pending_upload_id} is being finalized"
            )
        try:
            return self._finalize_locked(pending_upload_id, cache, db_session)
        finally:
            if lock.owned():
                lock.release()

    def _finalize_locked(
        self,
        pending_upload_id: str,
        cache: CacheBackend,
        db_session: Session | None,
    ) -> str:
        cache_key = _pending_upload_cache_key(pending_upload_id)
        raw = cache.get(cache_key)
        if raw is None:
            raise PresignedUploadNotFoundError(f"No pending upload {pending_upload_id}")
        pending = PendingPresignedUpload.model_validate_json(raw)

        stat = self._stat_object(pending.bucket_name, pending.object_key)
        # The pending upload stays, so finalize can run again after the upload.
        if stat is None:
            raise PresignedUploadVerificationError(
                f"File {pending.file_id} has not been uploaded"
            )
        mismatch = self._presigned_upload_mismatch(pending, stat)
        if mismatch is not None:
            cache.delete(cache_key)
            try:
                self._delete_object(pending.bucket_name, pending.object_key)
            except Exception:
                logger.warning(
                    "Failed to delete rejected upload %s/%s",
                    pending.bucket_name,
                    pending.object_key,
                    exc_info=True,
                )
            raise PresignedUploadVerificationError(f"File {pending.file_id} {mismatch}")

        with get_session_with_current_tenant_if_none(db_session) as db_session:
            upsert_filerecord(
                file_id=pending.file_id,
                display_name=pending.display_name or pending.file_id,
                file_origin=pending.file_origin,
                file_type=pending.file_type,
                bucket_name=pending.bucket_name,
                object_key=pending.object_key,
                db_session=db_session,
                file_size=pending.size,
            )
            db_session.commit()
        self._on_presigned_upload_finalized(pending.bucket_name, pending.object_key)
        cache.delete(cache_key)
        return pending.file_id

    def _presigned_upload_mismatch(
        self, pending: PendingPresignedUpload, stat: StoredObjectStat
    ) -> str | None:
        if stat.size != pending.size:
            return f"has {stat.size} bytes, expected {pending.size}"
        sha256 = stat.sha256
        # A store that keeps no SHA-256 (GCS, Azure) has the object read once.
        if sha256 is None:
            digest = hashlib.sha256()
            for chunk in self._read_object_chunks(
                pending.bucket_name, pending.object_key
            ):
                digest.update(chunk)
            sha256 = digest.hexdigest()
        if sha256 != pending.sha256:
            return "does not match the expected SHA-256"
        return None


class S3BackedFileStore(PresignableFileStore):
    """Isn't necessarily S3, but is any S3-compatible storage (e.g. MinIO)"""

    def __init__(
        self,
        bucket_name: str,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_region_name: str | None = None,
        s3_endpoint_url: str | None = None,
        s3_prefix: str | None = None,
        s3_verify_ssl: bool = True,
        legacy_endpoint_url: str | None = None,
        legacy_access_key_id: str | None = None,
        legacy_secret_access_key: str | None = None,
    ) -> None:
        self._s3_client: "S3Client | None" = None
        self._presign_s3_client: "S3Client | None" = None
        self._legacy_s3_client: "S3Client | None" = None
        # The store is shared across threads and its clients are built lazily,
        # so the first operations of several threads build each client once.
        self._client_lock = threading.Lock()
        self._bucket_name = bucket_name
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_region_name = aws_region_name or "us-east-2"
        self._s3_endpoint_url = s3_endpoint_url
        self._s3_prefix = s3_prefix or "onyx-files"
        self._s3_verify_ssl = s3_verify_ssl
        self._legacy_endpoint_url = legacy_endpoint_url
        self._legacy_access_key_id = legacy_access_key_id
        self._legacy_secret_access_key = legacy_secret_access_key

    def _get_s3_client(self) -> "S3Client":
        with self._client_lock:
            if self._s3_client is None:
                self._s3_client = build_s3_client(
                    self._s3_endpoint_url,
                    self._aws_access_key_id,
                    self._aws_secret_access_key,
                    self._aws_region_name,
                    self._s3_verify_ssl,
                )
            return self._s3_client

    def _get_presign_s3_client(self) -> "S3Client":
        with self._client_lock:
            if self._presign_s3_client is None:
                self._presign_s3_client = build_s3_client(
                    self._s3_endpoint_url,
                    self._aws_access_key_id,
                    self._aws_secret_access_key,
                    self._aws_region_name,
                    self._s3_verify_ssl,
                    signs_urls=True,
                )
            return self._presign_s3_client

    def _get_legacy_s3_client(self) -> "S3Client | None":
        if self._legacy_endpoint_url is None:
            return None
        with self._client_lock:
            if self._legacy_s3_client is None:
                self._legacy_s3_client = build_s3_client(
                    self._legacy_endpoint_url,
                    self._legacy_access_key_id,
                    self._legacy_secret_access_key,
                    self._aws_region_name,
                    self._s3_verify_ssl,
                    fail_fast=True,
                )
            return self._legacy_s3_client

    # Writes and deletes skip a retired legacy store. Reads still fall back to
    # it while MinIO runs, so a late write of an older release stays readable.
    def _get_legacy_write_client(self) -> "S3Client | None":
        legacy_client = self._get_legacy_s3_client()
        if legacy_client is None or self._legacy_store_retired():
            return None
        return legacy_client

    def _legacy_store_retired(self) -> bool:
        return legacy_store_retired(self._get_s3_client(), self._get_bucket_name())

    # Objects written before the bundled object store stay in the legacy
    # MinIO until they are copied across, so a miss falls back there.
    def _with_legacy_fallback(self, call: Callable[["S3Client"], _T]) -> _T:
        try:
            return call(self._get_s3_client())
        except ClientError as e:
            legacy_client = self._get_legacy_s3_client()
            if legacy_client is None or not is_missing_object(e):
                raise
            try:
                return call(legacy_client)
            except ClientError as legacy_error:
                # A legacy bucket no write has created yet holds nothing.
                if s3_error_code(legacy_error) == "NoSuchBucket":
                    raise e from legacy_error
                raise
            except Exception as legacy_error:
                # A retired MinIO may be stopped, so the object store's miss stands.
                if self._legacy_store_retired():
                    raise e from legacy_error
                raise

    # A rollback to a release that reads only the legacy store still finds
    # files written since the upgrade. The primary write already succeeded,
    # so a legacy failure logs and marks the key for a later replay into MinIO.
    def _put_legacy_object(
        self,
        bucket: str,
        key: str,
        body: "BlobTypeDef",
        content_type: str,
        kwargs: S3PutKwargs,
    ) -> None:
        try:
            legacy_client = self._get_legacy_write_client()
            if legacy_client is None:
                return
            put = partial(
                legacy_client.put_object,
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata={DUAL_WRITE_METADATA_KEY: "1"},
                **kwargs,
            )
            try:
                put()
            except ClientError as e:
                # A fresh install's MinIO starts without the bucket.
                if s3_error_code(e) != "NoSuchBucket":
                    raise
                ensure_bucket(legacy_client, bucket)
                put()
        except Exception:
            logger.warning(
                "Failed to write %s to the legacy MinIO store", key, exc_info=True
            )
            self._mark_legacy_out_of_sync(bucket, key)

    # A copy of MinIO into the object store takes only objects a file record
    # points at, so an object a failed delete leaves in MinIO never comes back.
    def _delete_legacy_object(self, bucket: str, key: str) -> None:
        try:
            legacy_client = self._get_legacy_write_client()
            if legacy_client is None:
                return
            legacy_client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            logger.warning(
                "Failed to delete %s from the legacy MinIO store", key, exc_info=True
            )

    def _mark_legacy_out_of_sync(self, bucket: str, key: str) -> None:
        try:
            # A unique body gives each marker its own ETag, so a replay removes
            # only the marker it resynced.
            self._get_s3_client().put_object(
                Bucket=bucket,
                Key=LEGACY_OUT_OF_SYNC_PREFIX + key,
                Body=uuid.uuid4().hex.encode(),
            )
        except Exception:
            logger.warning(
                "Failed to record that %s is out of sync in the legacy MinIO store",
                key,
                exc_info=True,
            )

    def _get_bucket_name(self) -> str:
        """Get S3 bucket name from configuration"""
        if not self._bucket_name:
            raise RuntimeError("S3 bucket name is required for S3 file store")
        return self._bucket_name

    def _get_s3_key(self, file_name: str) -> str:
        """Generate S3 key from file name with tenant ID prefix"""
        tenant_id = get_current_tenant_id()

        s3_key = generate_s3_key(
            file_name=file_name,
            prefix=self._s3_prefix,
            tenant_id=tenant_id,
            max_key_length=1024,
        )

        # Log if truncation occurred (when the key is exactly at the limit)
        if len(s3_key) == 1024:
            logger.info("File name was too long and was truncated: %s", file_name)

        return s3_key

    def initialize(self) -> None:
        """Initialize the S3 file store by ensuring the bucket exists"""
        ensure_bucket(self._get_s3_client(), self._get_bucket_name())

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

        s3_client = self._get_s3_client()
        bucket_name = self._get_bucket_name()
        s3_key = self._get_s3_key(file_id)

        hash256 = ""
        sha256_hash = hashlib.sha256()
        kwargs: S3PutKwargs = {}

        # FIX: Optimize checksum generation to avoid creating extra copies in memory
        # Read content from IO object
        if hasattr(content, "read"):
            file_content = content.read()
            if S3_GENERATE_LOCAL_CHECKSUM:
                # FIX: Don't convert to string first (creates unnecessary copy)
                # Work directly with bytes
                if isinstance(file_content, bytes):
                    sha256_hash.update(file_content)
                else:
                    sha256_hash.update(str(file_content).encode())
                hash256 = sha256_hash.hexdigest()
                kwargs["ChecksumSHA256"] = hash256
            if hasattr(content, "seek"):
                content.seek(0)  # Reset position for potential re-reads
        else:
            file_content = content

        # Upload to S3

        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=file_content,
            ContentType=file_type,
            **kwargs,
        )
        self._put_legacy_object(bucket_name, s3_key, file_content, file_type, kwargs)

        with get_session_with_current_tenant_if_none(db_session) as db_session:
            # Save metadata to database
            upsert_filerecord(
                file_id=file_id,
                display_name=display_name or file_id,
                file_origin=file_origin,
                file_type=file_type,
                bucket_name=bucket_name,
                object_key=s3_key,
                db_session=db_session,
                file_metadata=file_metadata,
                file_size=content_byte_size(file_content),
            )
            db_session.commit()

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

        try:
            response = self._with_legacy_fallback(
                lambda client: client.get_object(
                    Bucket=file_record.bucket_name, Key=file_record.object_key
                )
            )
        except ClientError:
            logger.error("Failed to read file %s from S3", file_id)
            raise

        # FIX: Stream file content instead of loading entire file into memory
        # This prevents OOM issues with large files (500MB+ PDFs, etc.)
        if use_tempfile:
            # Stream directly to temp file to avoid holding entire file in memory
            temp_file = tempfile.NamedTemporaryFile(mode="w+b", delete=True)
            # Stream in 8MB chunks to reduce memory footprint
            for chunk in response["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
                temp_file.write(chunk)
            temp_file.seek(0)
            return temp_file
        else:
            # For BytesIO, we still need to read into memory (legacy behavior)
            # but at least we're not creating duplicate copies
            file_content = response["Body"].read()
            return BytesIO(file_content)

    def read_file_record(
        self, file_id: str, db_session: Session | None = None
    ) -> FileStoreModel:
        with get_session_with_current_tenant_if_none(db_session) as db_session:
            file_record = get_filerecord_by_file_id(
                file_id=file_id, db_session=db_session
            )
        return file_record

    def get_file_size(
        self, file_id: str, db_session: Session | None = None
    ) -> int | None:
        """
        Get the size of a file in bytes by querying S3 metadata.
        """
        try:
            with get_session_with_current_tenant_if_none(db_session) as db_session:
                file_record = get_filerecord_by_file_id(
                    file_id=file_id, db_session=db_session
                )

            response = self._with_legacy_fallback(
                lambda client: client.head_object(
                    Bucket=file_record.bucket_name, Key=file_record.object_key
                )
            )
            return response.get("ContentLength")
        except ClientError as e:
            if is_missing_object(e):
                raise FileNotFoundError(
                    f"Object for file {file_id} does not exist"
                ) from e
            logger.warning("Error getting file size for %s: %s", file_id, e)
            return None
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
                        "File record %s with key %s has no bucket name, cannot delete from filestore",
                        file_id,
                        file_record.object_key,
                    )
                    db_session.commit()
                    return

                # Delete from external storage
                self._delete_legacy_object(
                    file_record.bucket_name, file_record.object_key
                )
                s3_client = self._get_s3_client()
                try:
                    s3_client.delete_object(
                        Bucket=file_record.bucket_name, Key=file_record.object_key
                    )
                except ClientError as e:
                    # If the object doesn't exist in file store, treat it as success
                    # since the end goal (object not existing) is achieved
                    if is_missing_object(e):
                        logger.warning(
                            "delete_file: File %s not found in file store (key: %s), cleaning up database record.",
                            file_id,
                            file_record.object_key,
                        )
                    else:
                        raise

                db_session.commit()

            except Exception:
                db_session.rollback()
                raise

    def change_file_id(
        self, old_file_id: str, new_file_id: str, db_session: Session | None = None
    ) -> bool:
        """Rename a file by repointing its DB record at the existing object.

        The object is not moved — only file_id changes — and reads resolve via
        the stored object_key, so they still find it. The object keeps its
        original key, so a file_id must not be reused for a new save_file after
        it has been renamed (the new write would overwrite the renamed object).
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
        """
        List all file IDs that start with the given prefix.
        """
        with get_session_with_current_tenant() as db_session:
            file_records = get_filerecord_by_prefix(
                prefix=prefix, db_session=db_session
            )
        return file_records

    def _presign_bucket_name(self) -> str:
        return self._get_bucket_name()

    def _presign_object_key(self, file_id: str) -> str:
        return self._get_s3_key(file_id)

    def _sign_download(
        self, bucket_name: str, object_key: str, ttl_seconds: int
    ) -> PresignedRequest:
        # Clients cannot reach the legacy MinIO store, so a file not yet copied
        # out of it is streamed with read_file instead.
        if (
            self._legacy_endpoint_url is not None
            and self._stat_object(bucket_name, object_key) is None
        ):
            raise PresignedUrlsNotSupportedError(
                f"{bucket_name}/{object_key} is not in the object store "
                "(it may exist only in the legacy MinIO store)"
            )
        expires_at = presign_expiry(ttl_seconds)
        url = self._get_presign_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=ttl_seconds,
        )
        return PresignedRequest(
            url=url, method="GET", headers={}, expires_at=expires_at
        )

    def _sign_upload(
        self, pending: PendingPresignedUpload, ttl_seconds: int
    ) -> PresignedRequest:
        # The signature covers the length and checksum, so the URL can only
        # ever write the expected bytes.
        checksum = base64.b64encode(bytes.fromhex(pending.sha256)).decode()
        expires_at = presign_expiry(ttl_seconds)
        url = self._get_presign_s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": pending.bucket_name,
                "Key": pending.object_key,
                "ContentType": pending.file_type,
                "ContentLength": pending.size,
                "ChecksumSHA256": checksum,
            },
            ExpiresIn=ttl_seconds,
        )
        return PresignedRequest(
            url=url,
            method="PUT",
            headers={
                "Content-Type": pending.file_type,
                "Content-Length": str(pending.size),
                "x-amz-checksum-sha256": checksum,
            },
            expires_at=expires_at,
        )

    def _stat_object(
        self, bucket_name: str, object_key: str
    ) -> StoredObjectStat | None:
        try:
            head = self._get_s3_client().head_object(
                Bucket=bucket_name, Key=object_key, ChecksumMode="ENABLED"
            )
        except ClientError as e:
            if is_missing_object(e):
                return None
            raise
        checksum = head.get("ChecksumSHA256")
        # A multipart checksum ends in "-<parts>" and is not the content hash.
        sha256 = (
            base64.b64decode(checksum).hex()
            if checksum is not None and "-" not in checksum
            else None
        )
        return StoredObjectStat(size=head["ContentLength"], sha256=sha256)

    def _read_object_chunks(self, bucket_name: str, object_key: str) -> Iterator[bytes]:
        body = self._get_s3_client().get_object(Bucket=bucket_name, Key=object_key)[
            "Body"
        ]
        try:
            yield from body.iter_chunks(chunk_size=PRESIGN_READ_CHUNK_BYTES)
        finally:
            body.close()

    def _delete_object(self, bucket_name: str, object_key: str) -> None:
        self._get_s3_client().delete_object(Bucket=bucket_name, Key=object_key)

    # A presigned PUT skips the dual write, so the object is marked out of
    # sync, and the legacy replay loop copies it into MinIO.
    def _on_presigned_upload_finalized(self, bucket_name: str, object_key: str) -> None:
        try:
            if self._get_legacy_write_client() is None:
                return
        except Exception:
            logger.warning(
                "Could not reach the legacy MinIO store for %s",
                object_key,
                exc_info=True,
            )
        self._mark_legacy_out_of_sync(bucket_name, object_key)


def get_s3_file_store() -> S3BackedFileStore:
    """
    Returns the S3 file store implementation.
    """

    # Get bucket name - this is required
    bucket_name = S3_FILE_STORE_BUCKET_NAME
    if not bucket_name:
        raise RuntimeError(
            "S3_FILE_STORE_BUCKET_NAME configuration is required for S3 file store"
        )

    return S3BackedFileStore(
        bucket_name=bucket_name,
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY,
        aws_region_name=AWS_REGION_NAME,
        s3_endpoint_url=S3_ENDPOINT_URL,
        s3_prefix=S3_FILE_STORE_PREFIX,
        s3_verify_ssl=S3_VERIFY_SSL,
        legacy_endpoint_url=S3_LEGACY_ENDPOINT_URL,
        legacy_access_key_id=S3_LEGACY_AWS_ACCESS_KEY_ID,
        legacy_secret_access_key=S3_LEGACY_AWS_SECRET_ACCESS_KEY,
    )


def get_gcs_file_store() -> "GCSBackedFileStore":
    """Returns the GCS file store implementation."""
    from onyx.configs.app_configs import (
        GCS_FILE_STORE_BUCKET_NAME,
        GCS_FILE_STORE_PREFIX,
        GCS_PROJECT_ID,
        GCS_SERVICE_ACCOUNT_KEY_JSON,
        GCS_SERVICE_ACCOUNT_KEY_PATH,
    )
    from onyx.file_store.gcs_file_store import GCSBackedFileStore

    bucket_name = GCS_FILE_STORE_BUCKET_NAME
    if not bucket_name:
        raise RuntimeError("GCS_FILE_STORE_BUCKET_NAME is required for GCS file store")

    return GCSBackedFileStore(
        bucket_name=bucket_name,
        gcs_prefix=GCS_FILE_STORE_PREFIX,
        project_id=GCS_PROJECT_ID,
        service_account_key_path=GCS_SERVICE_ACCOUNT_KEY_PATH,
        service_account_key_json=GCS_SERVICE_ACCOUNT_KEY_JSON,
    )


def get_azure_file_store() -> "AzureBlobBackedFileStore":
    """Returns the Azure Blob Storage file store implementation."""
    from onyx.configs.app_configs import (
        AZURE_FILE_STORE_CONTAINER_NAME,
        AZURE_FILE_STORE_PREFIX,
        AZURE_STORAGE_ACCOUNT_KEY,
        AZURE_STORAGE_ACCOUNT_NAME,
        AZURE_STORAGE_ACCOUNT_URL,
        AZURE_STORAGE_CONNECTION_STRING,
    )
    from onyx.file_store.azure_blob_file_store import AzureBlobBackedFileStore

    container_name = AZURE_FILE_STORE_CONTAINER_NAME
    if not container_name:
        raise RuntimeError(
            "AZURE_FILE_STORE_CONTAINER_NAME is required for Azure file store"
        )

    return AzureBlobBackedFileStore(
        container_name=container_name,
        azure_prefix=AZURE_FILE_STORE_PREFIX,
        account_name=AZURE_STORAGE_ACCOUNT_NAME,
        account_url=AZURE_STORAGE_ACCOUNT_URL,
        connection_string=AZURE_STORAGE_CONNECTION_STRING,
        account_key=AZURE_STORAGE_ACCOUNT_KEY,
    )


# Built once per process: a store carries no tenant or request state (keys take
# the tenant from the context at call time) and its client is safe to share,
# while building one costs tens of milliseconds, mostly the S3 client.
_DEFAULT_FILE_STORE: FileStore | None = None
_DEFAULT_FILE_STORE_LOCK: threading.Lock = threading.Lock()


def get_default_file_store() -> FileStore:
    global _DEFAULT_FILE_STORE
    with _DEFAULT_FILE_STORE_LOCK:
        if _DEFAULT_FILE_STORE is None:
            _DEFAULT_FILE_STORE = _build_default_file_store()
        return _DEFAULT_FILE_STORE


def _build_default_file_store() -> FileStore:
    """
    Returns the configured file store implementation based on FILE_STORE_BACKEND.

    When FILE_STORE_BACKEND=postgres:
    - Files are stored in PostgreSQL using Large Objects.
    - No external storage service (S3/MinIO) is required.

    When FILE_STORE_BACKEND=s3 (default):
    - Supports AWS S3, MinIO, and other S3-compatible storage.
    - Configuration via environment variables:
      - S3_FILE_STORE_BUCKET_NAME, S3_ENDPOINT_URL, S3_AWS_ACCESS_KEY_ID, etc.

    When FILE_STORE_BACKEND=gcs:
    - Uses Google Cloud Storage with ADC/Workload Identity or service account keys.
    - Configuration via environment variables:
      - GCS_FILE_STORE_BUCKET_NAME, GCS_PROJECT_ID, GCS_SERVICE_ACCOUNT_KEY_PATH, etc.

    When FILE_STORE_BACKEND=azure:
    - Uses Azure Blob Storage with connection string, account key, or
      DefaultAzureCredential (AKS Workload Identity / managed identity).
    - Configuration via environment variables:
      - AZURE_FILE_STORE_CONTAINER_NAME, AZURE_STORAGE_ACCOUNT_NAME,
        AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_ACCOUNT_KEY, etc.
    """
    from onyx.configs.app_configs import FILE_STORE_BACKEND
    from onyx.configs.constants import FileStoreType

    backend = FileStoreType(FILE_STORE_BACKEND)

    if backend == FileStoreType.POSTGRES:
        from onyx.file_store.postgres_file_store import PostgresBackedFileStore

        return PostgresBackedFileStore()

    if backend == FileStoreType.GCS:
        return get_gcs_file_store()

    if backend == FileStoreType.AZURE:
        return get_azure_file_store()

    return get_s3_file_store()
