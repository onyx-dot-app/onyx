import hashlib
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import partial
from io import BytesIO
from typing import IO, TYPE_CHECKING, Any, NotRequired, TypedDict, TypeVar, cast

import puremagic
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    AWS_REGION_NAME,
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
    get_filerecord_by_file_id_optional,
    get_filerecord_by_prefix,
    upsert_filerecord,
)
from onyx.db.models import FileRecord
from onyx.db.models import FileRecord as FileStoreModel
from onyx.file_store.s3_key_utils import generate_s3_key
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.literals import BucketLocationConstraintType

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


class S3PutKwargs(TypedDict):
    ChecksumSHA256: NotRequired[str]


# Marks legacy objects this release writes. The object store already holds that
# version or a newer one, so the copy never lets a marked object replace an app write.
DUAL_WRITE_METADATA_KEY = "onyx-dual-write"


def s3_error_code(e: ClientError) -> str | None:
    return e.response.get("Error", {}).get("Code")


def is_missing_object(e: ClientError) -> bool:
    return s3_error_code(e) in ("404", "NoSuchKey", "NotFound")


# `legacy_copy --retire` writes this object once MinIO holds nothing the object
# store lacks, so running processes stop writing to MinIO without a restart.
LEGACY_RETIRED_MARKER_KEY = "onyx-legacy-minio-retired"
LEGACY_RETIRED_RECHECK_SECONDS = 60
_legacy_retired: dict[tuple[str | None, str], tuple[float, bool]] = {}


def legacy_store_retired(
    client: "S3Client", endpoint_url: str | None, bucket: str
) -> bool:
    """Whether the retire marker is in the bucket, checked at most once a
    minute per store. A failed check keeps the last answer."""
    checked_at, retired = _legacy_retired.get(
        (endpoint_url, bucket), (float("-inf"), False)
    )
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
    _legacy_retired[(endpoint_url, bucket)] = (now, retired)
    return retired


def build_s3_client(
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    region_name: str,
    verify_ssl: bool,
    fail_fast: bool = False,
) -> "S3Client":
    try:
        # Imported here: boto3 costs ~16 MB and most workers never build an S3 client.
        import boto3
        from botocore.config import Config

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": region_name,
        }

        # An endpoint URL means a self-hosted store, which needs path-style addressing.
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
            config = Config(signature_version="s3v4", s3={"addressing_style": "path"})
            # A hung secondary store must not hold up the request it serves.
            if fail_fast:
                config = config.merge(
                    Config(
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"total_max_attempts": 2},
                    )
                )
            client_kwargs["config"] = config
            # Disable SSL verification if requested (for local development)
            if not verify_ssl:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                client_kwargs["verify"] = False

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
        raise RuntimeError(f"Failed to initialize S3 client: {e}")


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
            )
        if error_code != "404":
            logger.error("Failed to check S3 bucket '%s': %s", bucket_name, e)
            raise RuntimeError(f"Failed to check S3 bucket '{bucket_name}': {e}")

    logger.info("Creating S3 bucket '%s'", bucket_name)
    region = s3_client.meta.region_name
    # AWS needs a LocationConstraint outside us-east-1.
    if region and region != "us-east-1":
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
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
    def change_file_id(self, old_file_id: str, new_file_id: str) -> None:
        """
        Change the file ID of an existing file.

        Parameters:
        - old_file_id: Current file ID
        - new_file_id: New file ID to assign
        """
        raise NotImplementedError

    @abstractmethod
    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        """
        List all file IDs that start with the given prefix.
        """


class S3BackedFileStore(FileStore):
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
        self._legacy_s3_client: "S3Client | None" = None
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
        if self._s3_client is None:
            self._s3_client = build_s3_client(
                self._s3_endpoint_url,
                self._aws_access_key_id,
                self._aws_secret_access_key,
                self._aws_region_name,
                self._s3_verify_ssl,
            )
        return self._s3_client

    def _get_legacy_s3_client(self) -> "S3Client | None":
        if self._legacy_endpoint_url is None:
            return None
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
    # it, so a late write of an older release stays readable until it is copied.
    def _get_legacy_write_client(self) -> "S3Client | None":
        legacy_client = self._get_legacy_s3_client()
        if legacy_client is None or self._legacy_store_retired():
            return None
        return legacy_client

    def _legacy_store_retired(self) -> bool:
        return legacy_store_retired(
            self._get_s3_client(), self._s3_endpoint_url, self._get_bucket_name()
        )

    # Objects written before the bundled object store stay in the legacy
    # MinIO until the copy reaches them, so a miss falls back there.
    def _with_legacy_fallback(self, call: Callable[["S3Client"], _T]) -> _T:
        try:
            return call(self._get_s3_client())
        except ClientError as e:
            legacy_client = self._get_legacy_s3_client()
            if legacy_client is None or not is_missing_object(e):
                raise
            try:
                return call(legacy_client)
            except ClientError:
                raise
            except Exception as legacy_error:
                # A retired MinIO may be stopped, so the object store's miss stands.
                if self._legacy_store_retired():
                    raise e from legacy_error
                raise

    # A rollback to a release that reads only the legacy store still finds
    # files written since the upgrade. The primary write already succeeded,
    # so a legacy failure only logs.
    def _put_legacy_object(
        self,
        bucket: str,
        key: str,
        body: Any,
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

    # Without this the copy would bring a deleted file back as an orphan. It runs
    # before the primary delete, so a copy that races the delete finds the legacy
    # object gone and removes its own copy. A legacy failure only logs.
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
                        "File record %s with key %s has no bucket name, cannot delete from filestore",
                        file_id,
                        file_record.object_key,
                    )
                    delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
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

                # Delete metadata from database
                delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)

                db_session.commit()

            except Exception:
                db_session.rollback()
                raise

    def change_file_id(
        self, old_file_id: str, new_file_id: str, db_session: Session | None = None
    ) -> None:
        """Rename a file by repointing its DB record at the existing object.

        The object is not moved — only file_id changes — and reads resolve via
        the stored object_key, so they still find it. The object keeps its
        original key, so a file_id must not be reused for a new save_file after
        it has been renamed (the new write would overwrite the renamed object).
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

                # Reuse the old record's bucket/object_key — the object stays put.
                upsert_filerecord(
                    file_id=new_file_id,
                    display_name=old_file_record.display_name,
                    file_origin=old_file_record.file_origin,
                    file_type=old_file_record.file_type,
                    bucket_name=old_file_record.bucket_name,
                    object_key=old_file_record.object_key,
                    db_session=db_session,
                    file_metadata=file_metadata,
                    file_size=old_file_record.file_size,
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


def get_default_file_store() -> FileStore:
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
