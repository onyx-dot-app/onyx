import datetime
from collections.abc import Generator
from contextlib import nullcontext
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.file_store import S3BackedFileStore
from onyx.file_store.gcs_file_store import GCSBackedFileStore


class DBBaseTest(DeclarativeBase):
    pass


class FileRecord(DBBaseTest):
    __tablename__: str = "file_record"

    # Internal file ID, must be unique across all files
    file_id: Mapped[str] = mapped_column(String, primary_key=True)

    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    file_origin: Mapped[FileOrigin] = mapped_column(
        Enum(FileOrigin, native_enum=False), nullable=False
    )
    file_type: Mapped[str] = mapped_column(String, default="text/plain")

    # External storage support (S3, MinIO, Azure Blob, etc.)
    bucket_name: Mapped[str] = mapped_column(String, nullable=False)
    object_key: Mapped[str] = mapped_column(String, nullable=False)

    # Timestamps for external storage
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database for testing"""
    engine = create_engine("sqlite:///:memory:")
    DBBaseTest.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_content() -> bytes:
    """Sample file content for testing"""
    return b"This is a test file content"


@pytest.fixture
def sample_file_io(sample_content: bytes) -> BytesIO:
    """Sample file IO object for testing"""
    return BytesIO(sample_content)


class TestExternalStorageFileStore:
    """Test external storage file store functionality (S3-compatible)"""

    def test_get_default_file_store_s3(self) -> None:
        """Test that S3 file store is returned when backend is s3"""
        with patch("onyx.configs.app_configs.FILE_STORE_BACKEND", "s3"):
            file_store = get_default_file_store()
            assert isinstance(file_store, S3BackedFileStore)

    def test_s3_client_initialization_with_credentials(self) -> None:
        """Test S3 client initialization with explicit credentials"""
        with patch("boto3.client") as mock_boto3:
            file_store = S3BackedFileStore(
                bucket_name="test-bucket",
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",
                aws_region_name="us-west-2",
                s3_endpoint_url=None,
            )
            file_store._get_s3_client()

            # Verify boto3 client was called with the expected arguments
            mock_boto3.assert_called_once()
            call_kwargs: dict[str, Any] = mock_boto3.call_args[1]

            assert call_kwargs["service_name"] == "s3"
            assert call_kwargs["aws_access_key_id"] == "test-key"
            assert call_kwargs["aws_secret_access_key"] == "test-secret"
            assert call_kwargs["region_name"] == "us-west-2"

    def test_s3_client_initialization_with_iam_role(
        self,
        db_session: Session,  # noqa: ARG002
    ) -> None:
        """Test S3 client initialization with IAM role (no explicit credentials)"""
        with patch("boto3.client") as mock_boto3:
            file_store = S3BackedFileStore(
                bucket_name="test-bucket",
                aws_access_key_id=None,
                aws_secret_access_key=None,
                aws_region_name="us-west-2",
                s3_endpoint_url=None,
            )
            file_store._get_s3_client()

            # Verify boto3 client was called with the expected arguments
            mock_boto3.assert_called_once()
            call_kwargs: dict[str, Any] = mock_boto3.call_args[1]

            assert call_kwargs["service_name"] == "s3"
            assert call_kwargs["region_name"] == "us-west-2"
            # Should not have explicit credentials
            assert "aws_access_key_id" not in call_kwargs
            assert "aws_secret_access_key" not in call_kwargs

    def test_s3_bucket_name_configuration(self) -> None:
        """Test S3 bucket name configuration"""
        with patch(
            "onyx.file_store.file_store.S3_FILE_STORE_BUCKET_NAME", "my-test-bucket"
        ):
            file_store = S3BackedFileStore(bucket_name="my-test-bucket")
            bucket_name: str = file_store._get_bucket_name()
            assert bucket_name == "my-test-bucket"

    def test_s3_key_generation_default_prefix(self) -> None:
        """Test S3 key generation with default prefix"""
        with (
            patch("onyx.file_store.file_store.S3_FILE_STORE_PREFIX", "onyx-files"),
            patch(
                "onyx.file_store.file_store.get_current_tenant_id",
                return_value="test-tenant",
            ),
        ):
            file_store = S3BackedFileStore(bucket_name="test-bucket")
            s3_key: str = file_store._get_s3_key("test-file.txt")
            assert s3_key == "onyx-files/test-tenant/test-file.txt"

    def test_s3_key_generation_custom_prefix(self) -> None:
        """Test S3 key generation with custom prefix"""
        with (
            patch("onyx.file_store.file_store.S3_FILE_STORE_PREFIX", "custom-prefix"),
            patch(
                "onyx.file_store.file_store.get_current_tenant_id",
                return_value="test-tenant",
            ),
        ):
            file_store = S3BackedFileStore(
                bucket_name="test-bucket", s3_prefix="custom-prefix"
            )
            s3_key: str = file_store._get_s3_key("test-file.txt")
            assert s3_key == "custom-prefix/test-tenant/test-file.txt"

    def test_s3_key_generation_with_different_tenant_ids(self) -> None:
        """Test S3 key generation with different tenant IDs"""
        with patch("onyx.file_store.file_store.S3_FILE_STORE_PREFIX", "onyx-files"):
            file_store = S3BackedFileStore(bucket_name="test-bucket")

            # Test with tenant ID "tenant-1"
            with patch(
                "onyx.file_store.file_store.get_current_tenant_id",
                return_value="tenant-1",
            ):
                s3_key = file_store._get_s3_key("document.pdf")
                assert s3_key == "onyx-files/tenant-1/document.pdf"

            # Test with tenant ID "tenant-2"
            with patch(
                "onyx.file_store.file_store.get_current_tenant_id",
                return_value="tenant-2",
            ):
                s3_key = file_store._get_s3_key("document.pdf")
                assert s3_key == "onyx-files/tenant-2/document.pdf"

            # Test with default tenant (public)
            with patch(
                "onyx.file_store.file_store.get_current_tenant_id",
                return_value="public",
            ):
                s3_key = file_store._get_s3_key("document.pdf")
                assert s3_key == "onyx-files/public/document.pdf"

    @patch("boto3.client")
    def test_s3_save_file_mock(
        self,
        mock_boto3: MagicMock,
        db_session: Session,  # noqa: ARG002
        sample_file_io: BytesIO,
    ) -> None:
        """Test S3 file saving with mocked S3 client"""
        # Setup S3 mock
        mock_s3_client: Mock = Mock()
        mock_boto3.return_value = mock_s3_client

        # Create a mock database session
        mock_db_session: Mock = Mock()
        mock_db_session.commit = Mock()
        mock_db_session.rollback = Mock()

        with (
            patch(
                "onyx.file_store.file_store.S3_FILE_STORE_BUCKET_NAME", "test-bucket"
            ),
            patch("onyx.file_store.file_store.S3_FILE_STORE_PREFIX", "onyx-files"),
            patch("onyx.file_store.file_store.S3_AWS_ACCESS_KEY_ID", "test-key"),
            patch("onyx.file_store.file_store.S3_AWS_SECRET_ACCESS_KEY", "test-secret"),
        ):
            # Mock the database operation to avoid SQLAlchemy issues
            with patch("onyx.db.file_record.upsert_filerecord") as mock_upsert:
                mock_upsert.return_value = Mock()

                file_store = S3BackedFileStore(bucket_name="test-bucket")

                # This should not raise an exception
                file_store.save_file(
                    file_id="test-file.txt",
                    content=sample_file_io,
                    display_name="Test File",
                    file_origin=FileOrigin.OTHER,
                    file_type="text/plain",
                    db_session=mock_db_session,
                )

                # Verify S3 client was called correctly
                mock_s3_client.put_object.assert_called_once()
                call_args = mock_s3_client.put_object.call_args
                assert call_args[1]["Bucket"] == "test-bucket"
                assert call_args[1]["Key"] == "onyx-files/public/test-file.txt"
                assert call_args[1]["ContentType"] == "text/plain"

    def test_minio_client_initialization(self) -> None:
        """Test S3 client initialization with MinIO endpoint"""
        with (
            patch("boto3.client") as mock_boto3,
            patch("urllib3.disable_warnings"),
        ):
            file_store = S3BackedFileStore(
                bucket_name="test-bucket",
                aws_access_key_id="minioadmin",
                aws_secret_access_key="minioadmin",
                aws_region_name="us-east-1",
                s3_endpoint_url="http://localhost:9000",
                s3_verify_ssl=False,
            )
            file_store._get_s3_client()

            # Verify boto3 client was called with MinIO-specific settings
            mock_boto3.assert_called_once()
            call_kwargs: dict[str, Any] = mock_boto3.call_args[1]

            assert call_kwargs["service_name"] == "s3"
            assert call_kwargs["endpoint_url"] == "http://localhost:9000"
            assert call_kwargs["aws_access_key_id"] == "minioadmin"
            assert call_kwargs["aws_secret_access_key"] == "minioadmin"
            assert call_kwargs["region_name"] == "us-east-1"
            assert call_kwargs["verify"] is False

            # Verify S3 configuration for MinIO
            config = call_kwargs["config"]
            assert config.signature_version == "s3v4"
            assert config.s3["addressing_style"] == "path"

    def test_minio_ssl_verification_enabled(self) -> None:
        """Test MinIO with SSL verification enabled"""
        with patch("boto3.client") as mock_boto3:
            file_store = S3BackedFileStore(
                bucket_name="test-bucket",
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",
                s3_endpoint_url="https://minio.example.com",
                s3_verify_ssl=True,
            )
            file_store._get_s3_client()

            call_kwargs: dict[str, Any] = mock_boto3.call_args[1]
            # When SSL verification is enabled, verify should not be in kwargs (defaults to True)
            assert "verify" not in call_kwargs or call_kwargs.get("verify") is not False
            assert call_kwargs["endpoint_url"] == "https://minio.example.com"

    def test_aws_s3_without_endpoint_url(self) -> None:
        """Test that regular AWS S3 doesn't include endpoint URL or custom config"""
        with patch("boto3.client") as mock_boto3:
            file_store = S3BackedFileStore(
                bucket_name="test-bucket",
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",
                aws_region_name="us-west-2",
                s3_endpoint_url=None,
            )
            file_store._get_s3_client()

            call_kwargs: dict[str, Any] = mock_boto3.call_args[1]

            # For regular AWS S3, endpoint_url should not be present
            assert "endpoint_url" not in call_kwargs
            assert call_kwargs["service_name"] == "s3"
            assert call_kwargs["region_name"] == "us-west-2"
            # config should not be present for regular AWS S3
            assert "config" not in call_kwargs


class TestFileStoreInterface:
    """Test the general file store interface"""

    def test_file_store_s3_when_configured(self) -> None:
        """Test that S3 file store is returned when configured"""
        with patch("onyx.configs.app_configs.FILE_STORE_BACKEND", "s3"):
            file_store = get_default_file_store()
            assert isinstance(file_store, S3BackedFileStore)

    def test_file_store_postgres_when_configured(self) -> None:
        """Test that Postgres file store is returned when configured"""
        from onyx.file_store.postgres_file_store import PostgresBackedFileStore

        with patch("onyx.configs.app_configs.FILE_STORE_BACKEND", "postgres"):
            file_store = get_default_file_store()
            assert isinstance(file_store, PostgresBackedFileStore)

    def test_file_store_defaults_to_s3(self) -> None:
        """Test that the default backend is s3"""
        file_store = get_default_file_store()
        assert isinstance(file_store, S3BackedFileStore)

    def test_file_store_gcs_when_configured(self) -> None:
        """Test that GCS file store is returned when configured"""
        with (
            patch("onyx.configs.app_configs.FILE_STORE_BACKEND", "gcs"),
            patch(
                "onyx.configs.app_configs.GCS_FILE_STORE_BUCKET_NAME",
                "test-gcs-bucket",
            ),
        ):
            file_store = get_default_file_store()
            assert isinstance(file_store, GCSBackedFileStore)


class TestGCSFileStore:
    """Test GCS file store functionality"""

    def test_gcs_client_initialization_with_adc(self) -> None:
        """Test GCS client initialization with Application Default Credentials"""
        mock_client_instance = Mock()

        with patch(
            "google.cloud.storage.Client",
            return_value=mock_client_instance,
        ) as mock_client_cls:
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            client = file_store._get_gcs_client()

            # ADC path: no credentials, no project
            mock_client_cls.assert_called_once_with()
            assert client == mock_client_instance

    def test_gcs_client_initialization_with_key_path(self) -> None:
        """Test GCS client initialization with service account key file"""
        mock_credentials = Mock()
        mock_client_instance = Mock()

        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file",
                return_value=mock_credentials,
            ) as mock_from_file,
            patch(
                "google.cloud.storage.Client",
                return_value=mock_client_instance,
            ) as mock_client_cls,
        ):
            file_store = GCSBackedFileStore(
                bucket_name="test-bucket",
                service_account_key_path="/path/to/key.json",
                project_id="my-project",
            )
            client = file_store._get_gcs_client()

            mock_from_file.assert_called_once_with("/path/to/key.json")
            mock_client_cls.assert_called_once_with(
                credentials=mock_credentials, project="my-project"
            )
            assert client == mock_client_instance

    def test_gcs_client_initialization_with_key_json(self) -> None:
        """Test GCS client initialization with inline service account JSON"""
        mock_credentials = Mock()
        mock_client_instance = Mock()
        sa_json = '{"type":"service_account","project_id":"json-project"}'

        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_info",
                return_value=mock_credentials,
            ) as mock_from_info,
            patch(
                "google.cloud.storage.Client",
                return_value=mock_client_instance,
            ) as mock_client_cls,
        ):
            file_store = GCSBackedFileStore(
                bucket_name="test-bucket",
                service_account_key_json=sa_json,
            )
            client = file_store._get_gcs_client()

            mock_from_info.assert_called_once()
            # project_id should be extracted from the JSON when not explicitly set
            mock_client_cls.assert_called_once_with(
                credentials=mock_credentials, project="json-project"
            )
            assert client == mock_client_instance

    def test_gcs_object_key_generation(self) -> None:
        """Test GCS object key generation reuses S3 key utilities"""
        with patch(
            "onyx.file_store.gcs_file_store.get_current_tenant_id",
            return_value="test-tenant",
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            key: str = file_store._get_object_key("test-file.txt")
            assert key == "onyx-files/test-tenant/test-file.txt"

    def test_gcs_object_key_generation_custom_prefix(self) -> None:
        """Test GCS object key generation with custom prefix"""
        with patch(
            "onyx.file_store.gcs_file_store.get_current_tenant_id",
            return_value="test-tenant",
        ):
            file_store = GCSBackedFileStore(
                bucket_name="test-bucket", gcs_prefix="custom-prefix"
            )
            key: str = file_store._get_object_key("test-file.txt")
            assert key == "custom-prefix/test-tenant/test-file.txt"

    def test_gcs_save_file_mock(
        self,
        db_session: Session,  # noqa: ARG002
        sample_file_io: BytesIO,
    ) -> None:
        """Test GCS file saving with mocked GCS client"""
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        mock_db_session: Mock = Mock()
        mock_db_session.commit = Mock()
        mock_db_session.rollback = Mock()

        with patch("onyx.db.file_record.upsert_filerecord") as mock_upsert:
            mock_upsert.return_value = Mock()

            file_store = GCSBackedFileStore(bucket_name="test-gcs-bucket")
            file_store._gcs_client = mock_client

            file_store.save_file(
                file_id="test-file.txt",
                content=sample_file_io,
                display_name="Test File",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                db_session=mock_db_session,
            )

            mock_client.bucket.assert_called_once_with("test-gcs-bucket")
            mock_blob.upload_from_string.assert_called_once()
            call_args = mock_blob.upload_from_string.call_args
            assert call_args[1]["content_type"] == "text/plain"

    def test_gcs_bucket_name_required(self) -> None:
        """Test that get_gcs_file_store raises when no bucket name is configured"""
        from onyx.file_store.file_store import get_gcs_file_store

        with patch("onyx.configs.app_configs.GCS_FILE_STORE_BUCKET_NAME", ""):
            with pytest.raises(RuntimeError, match="GCS_FILE_STORE_BUCKET_NAME"):
                get_gcs_file_store()

    def test_gcs_read_file_mock(self, sample_content: bytes) -> None:
        """Test GCS read_file returns BytesIO with blob content"""
        mock_record = Mock(
            bucket_name="test-bucket", object_key="onyx-files/public/test-file.txt"
        )
        mock_blob = Mock()
        mock_blob.download_as_bytes.return_value = sample_content
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        mock_db_session = Mock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id",
                return_value=mock_record,
            ) as mock_get_record,
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            result = file_store.read_file(
                file_id="test-file.txt", db_session=mock_db_session
            )

            mock_get_record.assert_called_once_with(
                file_id="test-file.txt", db_session=mock_db_session
            )
            mock_client.bucket.assert_called_once_with("test-bucket")
            mock_bucket.blob.assert_called_once_with("onyx-files/public/test-file.txt")
            mock_blob.download_as_bytes.assert_called_once()
            assert result.read() == sample_content

    def test_gcs_read_file_with_tempfile(self, sample_content: bytes) -> None:
        """Test GCS read_file with use_tempfile=True downloads to a temp file"""
        mock_record = Mock(
            bucket_name="test-bucket", object_key="onyx-files/public/test-file.txt"
        )
        mock_blob = Mock()

        def fake_download_to_file(fp: Any) -> None:
            fp.write(sample_content)

        mock_blob.download_to_file.side_effect = fake_download_to_file
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        mock_db_session = Mock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id",
                return_value=mock_record,
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            result = file_store.read_file(
                file_id="test-file.txt",
                use_tempfile=True,
                db_session=mock_db_session,
            )

            mock_blob.download_to_file.assert_called_once()
            assert result.read() == sample_content
            result.close()

    def test_gcs_delete_file_mock(self) -> None:
        """Test GCS delete_file removes blob and DB record"""
        mock_record = Mock(
            bucket_name="test-bucket", object_key="onyx-files/public/test-file.txt"
        )
        mock_blob = Mock()
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id_optional",
                return_value=mock_record,
            ),
            patch(
                "onyx.file_store.gcs_file_store.delete_filerecord_by_file_id"
            ) as mock_delete_record,
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            file_store.delete_file(file_id="test-file.txt", db_session=mock_db_session)

            mock_blob.delete.assert_called_once()
            mock_delete_record.assert_called_once_with(
                file_id="test-file.txt", db_session=mock_db_session
            )
            mock_db_session.commit.assert_called_once()

    def test_gcs_delete_file_blob_not_found_in_gcs(self) -> None:
        """Test GCS delete_file proceeds with DB cleanup when blob is missing in GCS"""
        from google.api_core.exceptions import NotFound

        mock_record = Mock(
            bucket_name="test-bucket", object_key="onyx-files/public/missing.txt"
        )
        mock_blob = Mock()
        mock_blob.delete.side_effect = NotFound("blob not found")
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id_optional",
                return_value=mock_record,
            ),
            patch(
                "onyx.file_store.gcs_file_store.delete_filerecord_by_file_id"
            ) as mock_delete_record,
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            file_store.delete_file(file_id="missing.txt", db_session=mock_db_session)

            mock_delete_record.assert_called_once_with(
                file_id="missing.txt", db_session=mock_db_session
            )
            mock_db_session.commit.assert_called_once()

    def test_gcs_delete_file_missing_record_raises(self) -> None:
        """Test GCS delete_file raises when record is missing and error_on_missing=True"""
        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id_optional",
                return_value=None,
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")

            with pytest.raises(RuntimeError, match="does not exist or was deleted"):
                file_store.delete_file(
                    file_id="missing.txt", db_session=mock_db_session
                )

            mock_db_session.rollback.assert_called_once()

    def test_gcs_delete_file_missing_record_silent(self) -> None:
        """Test GCS delete_file returns silently when record is missing and error_on_missing=False"""
        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id_optional",
                return_value=None,
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store.delete_file(
                file_id="missing.txt",
                error_on_missing=False,
                db_session=mock_db_session,
            )

            mock_db_session.commit.assert_not_called()
            mock_db_session.rollback.assert_not_called()

    def test_gcs_change_file_id_mock(self) -> None:
        """Test GCS change_file_id copies blob, upserts new record, and deletes old"""
        mock_record = Mock(
            bucket_name="test-bucket",
            object_key="onyx-files/public/old-id",
            display_name="Old File",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_metadata=None,
        )
        mock_source_blob = Mock()
        mock_source_bucket = Mock()
        mock_source_bucket.blob.return_value = mock_source_blob
        mock_dest_bucket = Mock()

        mock_client = Mock()
        # First call returns source bucket, second returns destination bucket
        mock_client.bucket.side_effect = [mock_source_bucket, mock_dest_bucket]

        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id",
                return_value=mock_record,
            ),
            patch("onyx.file_store.gcs_file_store.upsert_filerecord") as mock_upsert,
            patch(
                "onyx.file_store.gcs_file_store.delete_filerecord_by_file_id"
            ) as mock_delete_record,
            patch(
                "onyx.file_store.gcs_file_store.get_current_tenant_id",
                return_value="public",
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            file_store.change_file_id(
                old_file_id="old-id",
                new_file_id="new-id",
                db_session=mock_db_session,
            )

            new_key = "onyx-files/public/new-id"
            mock_source_bucket.copy_blob.assert_called_once_with(
                mock_source_blob, mock_dest_bucket, new_key
            )
            mock_upsert.assert_called_once()
            assert mock_upsert.call_args.kwargs["file_id"] == "new-id"
            assert mock_upsert.call_args.kwargs["bucket_name"] == "test-bucket"
            assert mock_upsert.call_args.kwargs["object_key"] == new_key
            mock_delete_record.assert_called_once_with(
                file_id="old-id", db_session=mock_db_session
            )
            mock_db_session.commit.assert_called_once()
            mock_source_blob.delete.assert_called_once()
            # Source blob deletion must happen after the DB commit
            commit_call_order = mock_db_session.commit.call_args_list
            assert commit_call_order, "expected db_session.commit to have been called"

    def test_gcs_get_file_size_mock(self) -> None:
        """Test GCS get_file_size returns the blob size"""
        mock_record = Mock(
            bucket_name="test-bucket", object_key="onyx-files/public/test-file.txt"
        )
        mock_blob = Mock()
        mock_blob.size = 1234
        mock_bucket = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = Mock()
        mock_client.bucket.return_value = mock_bucket

        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id",
                return_value=mock_record,
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")
            file_store._gcs_client = mock_client

            size = file_store.get_file_size(
                file_id="test-file.txt", db_session=mock_db_session
            )

            mock_blob.reload.assert_called_once()
            assert size == 1234

    def test_gcs_get_file_size_returns_none_on_error(self) -> None:
        """Test GCS get_file_size swallows errors and returns None"""
        mock_db_session = MagicMock()

        with (
            patch(
                "onyx.file_store.gcs_file_store.get_session_with_current_tenant_if_none",
                return_value=nullcontext(mock_db_session),
            ),
            patch(
                "onyx.file_store.gcs_file_store.get_filerecord_by_file_id",
                side_effect=RuntimeError("record missing"),
            ),
        ):
            file_store = GCSBackedFileStore(bucket_name="test-bucket")

            size = file_store.get_file_size(
                file_id="missing.txt", db_session=mock_db_session
            )

            assert size is None

    def test_gcs_initialize_existing_bucket(self) -> None:
        """Test GCS initialize is a no-op when the bucket already exists"""
        mock_client = Mock()
        mock_client.get_bucket.return_value = Mock()

        file_store = GCSBackedFileStore(bucket_name="test-bucket")
        file_store._gcs_client = mock_client

        file_store.initialize()

        mock_client.get_bucket.assert_called_once_with("test-bucket")
        mock_client.create_bucket.assert_not_called()

    def test_gcs_initialize_creates_missing_bucket(self) -> None:
        """Test GCS initialize creates the bucket when it does not exist"""
        from google.api_core.exceptions import NotFound

        mock_client = Mock()
        mock_client.get_bucket.side_effect = NotFound("bucket not found")

        file_store = GCSBackedFileStore(bucket_name="test-bucket")
        file_store._gcs_client = mock_client

        file_store.initialize()

        mock_client.create_bucket.assert_called_once_with("test-bucket")

    def test_gcs_initialize_forbidden_raises(self) -> None:
        """Test GCS initialize raises RuntimeError on Forbidden access"""
        from google.api_core.exceptions import Forbidden

        mock_client = Mock()
        mock_client.get_bucket.side_effect = Forbidden("access denied")

        file_store = GCSBackedFileStore(bucket_name="test-bucket")
        file_store._gcs_client = mock_client

        with pytest.raises(RuntimeError, match="Access denied"):
            file_store.initialize()
