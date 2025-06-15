import tempfile
from abc import ABC
from abc import abstractmethod
from io import BytesIO
from typing import Any
from typing import cast
from typing import IO

import boto3
import puremagic
from botocore.config import Config
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client
from sqlalchemy.orm import Session

from onyx.configs.app_configs import AWS_ACCESS_KEY_ID
from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import AWS_SECRET_ACCESS_KEY
from onyx.configs.app_configs import MINIO_ACCESS_KEY
from onyx.configs.app_configs import MINIO_SECRET_KEY
from onyx.configs.app_configs import S3_ENDPOINT_URL
from onyx.configs.app_configs import S3_FILE_STORE_BUCKET_NAME
from onyx.configs.app_configs import S3_FILE_STORE_PREFIX
from onyx.configs.app_configs import S3_VERIFY_SSL
from onyx.configs.constants import FileOrigin
from onyx.db.models import FileStore as FileStoreModel
from onyx.db.pg_file_store import delete_filestore_by_file_name
from onyx.db.pg_file_store import get_filestore_by_file_name
from onyx.db.pg_file_store import get_filestore_by_file_name_optional
from onyx.db.pg_file_store import upsert_filestore_external
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger

logger = setup_logger()


class FileStore(ABC):
    """
    An abstraction for storing files and large binary objects.
    """

    @abstractmethod
    def initialize(self) -> None:
        """
        Should be called once before any other methods are called.
        """
        raise NotImplementedError

    @abstractmethod
    def has_file(
        self,
        file_name: str,
        file_origin: FileOrigin,
        file_type: str,
        display_name: str | None = None,
    ) -> bool:
        """
        Check if a file exists in the blob store

        Parameters:
        - file_name: Name of the file to save
        - display_name: Display name of the file
        - file_origin: Origin of the file
        - file_type: Type of the file
        """
        raise NotImplementedError

    @abstractmethod
    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save a file to the blob store

        Parameters:
        - connector_name: Name of the CC-Pair (as specified by the user in the UI)
        - file_name: Name of the file to save
        - content: Contents of the file
        - display_name: Display name of the file
        - file_origin: Origin of the file
        - file_type: Type of the file
        - file_metadata: Additional metadata for the file
        - commit: Whether to commit the transaction after saving the file
        """
        raise NotImplementedError

    @abstractmethod
    def read_file(
        self, file_name: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        """
        Read the content of a given file by the name

        Parameters:
        - file_name: Name of file to read
        - mode: Mode to open the file (e.g. 'b' for binary)
        - use_tempfile: Whether to use a temporary file to store the contents
                        in order to avoid loading the entire file into memory

        Returns:
            Contents of the file and metadata dict
        """

    @abstractmethod
    def read_file_record(self, file_name: str) -> FileStoreModel:
        """
        Read the file record by the name
        """

    @abstractmethod
    def delete_file(self, file_name: str) -> None:
        """
        Delete a file by its name.

        Parameters:
        - file_name: Name of file to delete
        """

    @abstractmethod
    def get_file_with_mime_type(self, filename: str) -> FileWithMimeType | None:
        """
        Get the file + parse out the mime type.
        """


class S3BackedFileStore(FileStore):
    """Isn't necessarily S3, but is any S3-compatible storage (e.g. MinIO)"""

    def __init__(
        self,
        db_session: Session,
        bucket_name: str,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_region_name: str | None = None,
        s3_endpoint_url: str | None = None,
        s3_prefix: str | None = None,
        s3_verify_ssl: bool = True,
    ) -> None:
        self.db_session = db_session
        self._s3_client: S3Client | None = None
        self._bucket_name = bucket_name
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_region_name = aws_region_name or "us-east-2"
        self._s3_endpoint_url = s3_endpoint_url
        self._s3_prefix = s3_prefix or "onyx-files"
        self._s3_verify_ssl = s3_verify_ssl

    def _get_s3_client(self) -> S3Client:
        """Initialize S3 client if not already done"""
        if self._s3_client is None:
            try:
                client_kwargs: dict[str, Any] = {
                    "service_name": "s3",
                    "region_name": self._aws_region_name,
                }

                # Add endpoint URL if specified (for MinIO, etc.)
                if self._s3_endpoint_url:
                    client_kwargs["endpoint_url"] = self._s3_endpoint_url
                    client_kwargs["config"] = Config(
                        signature_version="s3v4",
                        s3={"addressing_style": "path"},  # Required for MinIO
                    )
                    # Disable SSL verification if requested (for local development)
                    if not self._s3_verify_ssl:
                        import urllib3

                        urllib3.disable_warnings(
                            urllib3.exceptions.InsecureRequestWarning
                        )
                        client_kwargs["verify"] = False

                if self._aws_access_key_id and self._aws_secret_access_key:
                    # Use explicit credentials
                    client_kwargs.update(
                        {
                            "aws_access_key_id": self._aws_access_key_id,
                            "aws_secret_access_key": self._aws_secret_access_key,
                        }
                    )
                    self._s3_client = boto3.client(**client_kwargs)
                else:
                    # Use IAM role or default credentials (not typically used with MinIO)
                    self._s3_client = boto3.client(**client_kwargs)

            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
                raise RuntimeError(f"Failed to initialize S3 client: {e}")

        return self._s3_client

    def _get_bucket_name(self) -> str:
        """Get S3 bucket name from configuration"""
        if not self._bucket_name:
            raise RuntimeError("S3 bucket name is required for S3 file store")
        return self._bucket_name

    def _get_s3_key(self, file_name: str) -> str:
        """Generate S3 key from file name"""
        return f"{self._s3_prefix}/{file_name}"

    def initialize(self) -> None:
        """Initialize the S3 file store by ensuring the bucket exists"""
        try:
            s3_client = self._get_s3_client()
            bucket_name = self._get_bucket_name()

            # Check if bucket exists
            try:
                s3_client.head_bucket(Bucket=bucket_name)
                logger.info(f"S3 bucket '{bucket_name}' already exists")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "404":
                    # Bucket doesn't exist, create it
                    logger.info(f"Creating S3 bucket '{bucket_name}'")

                    # For AWS S3, we need to handle region-specific bucket creation
                    region = (
                        s3_client._client_config.region_name
                        if hasattr(s3_client, "_client_config")
                        else None
                    )

                    if region and region != "us-east-1":
                        # For regions other than us-east-1, we need to specify LocationConstraint
                        s3_client.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={"LocationConstraint": region},
                        )
                    else:
                        # For us-east-1 or MinIO/other S3-compatible services
                        s3_client.create_bucket(Bucket=bucket_name)

                    logger.info(f"Successfully created S3 bucket '{bucket_name}'")
                elif error_code == "403":
                    # Bucket exists but we don't have permission to access it
                    logger.warning(
                        f"S3 bucket '{bucket_name}' exists but access is forbidden"
                    )
                    raise RuntimeError(
                        f"Access denied to S3 bucket '{bucket_name}'. Check credentials and permissions."
                    )
                else:
                    # Some other error occurred
                    logger.error(f"Failed to check S3 bucket '{bucket_name}': {e}")
                    raise RuntimeError(
                        f"Failed to check S3 bucket '{bucket_name}': {e}"
                    )

        except Exception as e:
            logger.error(f"Failed to initialize S3 file store: {e}")
            raise RuntimeError(f"Failed to initialize S3 file store: {e}")

    def has_file(
        self,
        file_name: str,
        file_origin: FileOrigin,
        file_type: str,
        display_name: str | None = None,
    ) -> bool:
        file_record = get_filestore_by_file_name_optional(
            file_name=file_name, db_session=self.db_session
        )
        return (
            file_record is not None
            and file_record.file_origin == file_origin
            and file_record.file_type == file_type
            and file_record.bucket_name
            is not None  # Ensure it's an external storage file
            and file_record.object_key is not None
        )

    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            s3_client = self._get_s3_client()
            bucket_name = self._get_bucket_name()
            s3_key = self._get_s3_key(file_name)

            # Read content from IO object
            if hasattr(content, "read"):
                file_content = content.read()
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
            )

            # Save metadata to database
            upsert_filestore_external(
                file_name=file_name,
                display_name=display_name or file_name,
                file_origin=file_origin,
                file_type=file_type,
                bucket_name=bucket_name,
                object_key=s3_key,
                db_session=self.db_session,
                file_metadata=file_metadata,
            )
            self.db_session.commit()

        except Exception:
            self.db_session.rollback()
            raise

    def read_file(
        self, file_name: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        file_record = get_filestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )

        if file_record.bucket_name is None or file_record.object_key is None:
            raise RuntimeError(f"File {file_name} is not stored in external storage")

        s3_client = self._get_s3_client()

        try:
            response = s3_client.get_object(
                Bucket=file_record.bucket_name, Key=file_record.object_key
            )

            file_content = response["Body"].read()

            if use_tempfile:
                # Always open in binary mode for temp files since we're writing bytes
                temp_file = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
                temp_file.write(file_content)
                temp_file.seek(0)
                return temp_file
            else:
                return BytesIO(file_content)

        except ClientError as e:
            logger.error(f"Failed to read file {file_name} from S3: {e}")
            raise RuntimeError(f"Failed to read file {file_name} from S3: {e}")

    def read_file_record(self, file_name: str) -> FileStoreModel:
        file_record = get_filestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )
        return file_record

    def delete_file(self, file_name: str) -> None:
        try:
            file_record = get_filestore_by_file_name(
                file_name=file_name, db_session=self.db_session
            )

            if (
                file_record.bucket_name is not None
                and file_record.object_key is not None
            ):
                s3_client = self._get_s3_client()

                # Delete from external storage
                s3_client.delete_object(
                    Bucket=file_record.bucket_name, Key=file_record.object_key
                )

            # Delete metadata from database
            delete_filestore_by_file_name(
                file_name=file_name, db_session=self.db_session
            )

            self.db_session.commit()

        except Exception:
            self.db_session.rollback()
            raise

    def get_file_with_mime_type(self, filename: str) -> FileWithMimeType | None:
        mime_type: str = "application/octet-stream"
        try:
            file_io = self.read_file(filename, mode="b")
            file_content = file_io.read()
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)
            return FileWithMimeType(data=file_content, mime_type=mime_type)
        except Exception:
            return None


def get_default_file_store(db_session: Session) -> FileStore:
    """
    Returns the configured file store implementation.

    Supports AWS S3, MinIO, and other S3-compatible storage.

    Configuration is handled via environment variables defined in app_configs.py:

    AWS S3:
    - S3_FILE_STORE_BUCKET_NAME=<bucket-name>
    - S3_FILE_STORE_PREFIX=<prefix> (optional, defaults to 'onyx-files')
    - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (or use IAM roles)
    - AWS_REGION_NAME=<region> (optional, defaults to 'us-east-2')

    MinIO:
    - S3_FILE_STORE_BUCKET_NAME=<bucket-name>
    - S3_ENDPOINT_URL=<minio-endpoint> (e.g., http://localhost:9000)
    - MINIO_ACCESS_KEY=<minio-access-key> (falls back to AWS_ACCESS_KEY_ID)
    - MINIO_SECRET_KEY=<minio-secret-key> (falls back to AWS_SECRET_ACCESS_KEY)
    - AWS_REGION_NAME=<any-region> (optional, defaults to 'us-east-2')
    - S3_VERIFY_SSL=false (optional, for local development)

    Other S3-compatible storage (Digital Ocean, Linode, etc.):
    - Same as MinIO, but set appropriate S3_ENDPOINT_URL
    """
    # Get bucket name - this is required
    bucket_name = S3_FILE_STORE_BUCKET_NAME
    if not bucket_name:
        raise RuntimeError(
            "S3_FILE_STORE_BUCKET_NAME configuration is required for S3 file store"
        )

    # Try to get credentials from environment, prioritizing MinIO-specific ones
    aws_access_key_id = MINIO_ACCESS_KEY or AWS_ACCESS_KEY_ID
    aws_secret_access_key = MINIO_SECRET_KEY or AWS_SECRET_ACCESS_KEY

    return S3BackedFileStore(
        db_session=db_session,
        bucket_name=bucket_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_region_name=AWS_REGION_NAME,
        s3_endpoint_url=S3_ENDPOINT_URL,
        s3_prefix=S3_FILE_STORE_PREFIX,
        s3_verify_ssl=S3_VERIFY_SSL,
    )
