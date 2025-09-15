import datetime
from collections.abc import Generator
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


class TestDBBase(DeclarativeBase):
    pass


class FileRecord(TestDBBase):
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
    TestDBBase.metadata.create_all(engine)
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
        """Test that external storage file store is returned"""
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

    def test_s3_client_initialization_with_iam_role(self, db_session: Session) -> None:
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
        self, mock_boto3: MagicMock, db_session: Session, sample_file_io: BytesIO
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

    def test_file_store_always_external_storage(self) -> None:
        """Test that external storage file store is always returned"""
        # File store should always be S3BackedFileStore regardless of environment
        file_store = get_default_file_store()
        assert isinstance(file_store, S3BackedFileStore)
