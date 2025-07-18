import os
import time
import uuid
from collections.abc import Generator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Tuple
from typing import TypedDict
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.file_store.file_store import S3BackedFileStore
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID

logger = setup_logger()


TEST_BUCKET_NAME: str = "onyx-file-store-tests"
TEST_FILE_PREFIX: str = "test-files"


# Type definitions for test data
class BackendConfig(TypedDict):
    endpoint_url: str | None
    access_key: str
    secret_key: str
    region: str
    verify_ssl: bool
    backend_name: str


class FileTestData(TypedDict):
    name: str
    display_name: str
    content: str
    type: str
    origin: FileOrigin


class WorkerResult(TypedDict):
    worker_id: int
    file_name: str
    content: str


def _get_all_backend_configs() -> List[BackendConfig]:
    """Get configurations for all available backends"""
    from onyx.configs.app_configs import (
        S3_ENDPOINT_URL,
        S3_AWS_ACCESS_KEY_ID,
        S3_AWS_SECRET_ACCESS_KEY,
        AWS_REGION_NAME,
    )

    configs: List[BackendConfig] = []

    # MinIO configuration (if endpoint is configured)
    if S3_ENDPOINT_URL:
        minio_access_key = "minioadmin"
        minio_secret_key = "minioadmin"
        configs.append(
            {
                "endpoint_url": S3_ENDPOINT_URL,
                "access_key": minio_access_key,
                "secret_key": minio_secret_key,
                "region": "us-east-1",
                "verify_ssl": False,
                "backend_name": "MinIO",
            }
        )

    # AWS S3 configuration (if credentials are available)
    elif S3_AWS_ACCESS_KEY_ID and S3_AWS_SECRET_ACCESS_KEY:
        configs.append(
            {
                "endpoint_url": None,
                "access_key": S3_AWS_ACCESS_KEY_ID,
                "secret_key": S3_AWS_SECRET_ACCESS_KEY,
                "region": AWS_REGION_NAME or "us-east-2",
                "verify_ssl": True,
                "backend_name": "AWS S3",
            }
        )

    if not configs:
        pytest.skip(
            "No backend configurations available - set MinIO or AWS S3 credentials"
        )

    return configs


@pytest.fixture(
    scope="function",
    params=_get_all_backend_configs(),
    ids=lambda config: config["backend_name"],
)
def file_store(
    request: pytest.FixtureRequest, db_session: Session, tenant_context: None
) -> Generator[S3BackedFileStore, None, None]:
    """Create an S3BackedFileStore instance for testing with parametrized backend"""
    backend_config: BackendConfig = request.param

    # Create S3BackedFileStore with backend-specific configuration
    store = S3BackedFileStore(
        bucket_name=TEST_BUCKET_NAME,
        aws_access_key_id=backend_config["access_key"],
        aws_secret_access_key=backend_config["secret_key"],
        aws_region_name=backend_config["region"],
        s3_endpoint_url=backend_config["endpoint_url"],
        s3_prefix=f"{TEST_FILE_PREFIX}-{uuid.uuid4()}",
        s3_verify_ssl=backend_config["verify_ssl"],
    )

    # Initialize the store and ensure bucket exists
    store.initialize()
    logger.info(
        f"Successfully initialized {backend_config['backend_name']} file store with bucket {TEST_BUCKET_NAME}"
    )

    yield store

    # Cleanup: Remove all test files from the bucket (including tenant-prefixed files)
    try:
        s3_client = store._get_s3_client()
        actual_bucket_name = store._get_bucket_name()

        # List and delete all objects in the test prefix (including tenant subdirectories)
        response = s3_client.list_objects_v2(
            Bucket=actual_bucket_name, Prefix=f"{store._s3_prefix}/"
        )

        if "Contents" in response:
            objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]
            s3_client.delete_objects(
                Bucket=actual_bucket_name, Delete={"Objects": objects_to_delete}  # type: ignore[typeddict-item]
            )
            logger.info(
                f"Cleaned up {len(objects_to_delete)} test objects from {backend_config['backend_name']}"
            )
    except Exception as e:
        logger.warning(f"Failed to cleanup test objects: {e}")


class TestS3BackedFileStore:
    """Test suite for S3BackedFileStore using real S3-compatible storage (MinIO or AWS S3)"""

    def test_store_initialization(self, file_store: S3BackedFileStore) -> None:
        """Test that the file store initializes properly"""
        # The fixture already calls initialize(), so we just verify it worked
        bucket_name = file_store._get_bucket_name()
        assert bucket_name.startswith(TEST_BUCKET_NAME)  # Should be backend-specific

        # Verify bucket exists by trying to list objects
        s3_client = file_store._get_s3_client()

        # This should not raise an exception
        s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)

    def test_save_and_read_text_file(self, file_store: S3BackedFileStore) -> None:
        """Test saving and reading a text file"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Text File"
        content = "This is a test text file content.\nWith multiple lines."
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Save the file
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Read the file back
        read_content_io = file_store.read_file(file_id)
        read_content = read_content_io.read().decode("utf-8")

        assert read_content == content

        # Verify file record in database
        file_record = file_store.read_file_record(file_id)
        assert file_record.file_id == file_id
        assert file_record.display_name == display_name
        assert file_record.file_origin == file_origin
        assert file_record.file_type == file_type
        assert (
            file_record.bucket_name == file_store._get_bucket_name()
        )  # Use actual bucket name
        # The object key should include the tenant ID
        expected_object_key = f"{file_store._s3_prefix}/{TEST_TENANT_ID}/{file_id}"
        assert file_record.object_key == expected_object_key

    def test_save_and_read_binary_file(self, file_store: S3BackedFileStore) -> None:
        """Test saving and reading a binary file"""
        file_id = f"{uuid.uuid4()}.bin"
        display_name = "Test Binary File"
        # Create some binary content
        content = bytes(range(256))  # 0-255 bytes
        file_type = "application/octet-stream"
        file_origin = FileOrigin.CONNECTOR

        # Save the file
        content_io = BytesIO(content)
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Read the file back
        read_content_io = file_store.read_file(file_id)
        read_content = read_content_io.read()

        assert read_content == content

    def test_save_with_metadata(self, file_store: S3BackedFileStore) -> None:
        """Test saving a file with metadata"""
        file_id = f"{uuid.uuid4()}.json"
        display_name = "Test Metadata File"
        content = '{"key": "value", "number": 42}'
        file_type = "application/json"
        file_origin = FileOrigin.CHAT_UPLOAD
        metadata: Dict[str, Any] = {
            "source": "test_suite",
            "version": "1.0",
            "tags": ["test", "json"],
            "size": len(content),
        }

        # Save the file with metadata
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=metadata,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Verify metadata is stored in database
        file_record = file_store.read_file_record(file_id)
        assert file_record.file_metadata == metadata

    def test_has_file(self, file_store: S3BackedFileStore) -> None:
        """Test the has_file method"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Has File"
        content = "Content for has_file test"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Initially, file should not exist
        assert not file_store.has_file(
            file_id=file_id,
            file_origin=file_origin,
            file_type=file_type,
        )

        # Save the file
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Now file should exist
        assert file_store.has_file(
            file_id=file_id,
            file_origin=file_origin,
            file_type=file_type,
        )

        # Test with wrong parameters
        assert not file_store.has_file(
            file_id=file_id,
            file_origin=FileOrigin.CONNECTOR,  # Wrong origin
            file_type=file_type,
        )

        assert not file_store.has_file(
            file_id=file_id,
            file_origin=file_origin,
            file_type="application/pdf",  # Wrong type
        )

    def test_read_file_with_tempfile(self, file_store: S3BackedFileStore) -> None:
        """Test reading a file using temporary file"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Temp File"
        content = "Content for temporary file test"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Save the file
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Read using temporary file
        temp_file = file_store.read_file(file_id, use_tempfile=True)

        # Read content from temp file
        temp_file.seek(0)
        read_content_bytes = temp_file.read()
        if isinstance(read_content_bytes, bytes):
            read_content_str = read_content_bytes.decode("utf-8")
        else:
            read_content_str = str(read_content_bytes)

        assert read_content_str == content

        # Clean up the temp file
        temp_file.close()
        if hasattr(temp_file, "name"):
            try:
                os.unlink(temp_file.name)
            except (OSError, AttributeError):
                pass

    def test_delete_file(self, file_store: S3BackedFileStore) -> None:
        """Test deleting a file"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Delete File"
        content = "Content for delete test"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Save the file
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Verify file exists
        assert file_store.has_file(
            file_id=file_id,
            file_origin=file_origin,
            file_type=file_type,
        )

        # Delete the file
        file_store.delete_file(file_id)

        # Verify file no longer exists
        assert not file_store.has_file(
            file_id=file_id,
            file_origin=file_origin,
            file_type=file_type,
        )

        # Verify trying to read deleted file raises exception
        with pytest.raises(RuntimeError, match="does not exist or was deleted"):
            file_store.read_file(file_id)

    def test_get_file_with_mime_type(self, file_store: S3BackedFileStore) -> None:
        """Test getting file with mime type detection"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test MIME Type"
        content = "This is a plain text file"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Save the file
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Get file with mime type
        file_with_mime = file_store.get_file_with_mime_type(file_id)

        assert file_with_mime is not None
        assert file_with_mime.data.decode("utf-8") == content
        # The detected mime type might be different from what we stored
        assert file_with_mime.mime_type is not None

    def test_file_overwrite(self, file_store: S3BackedFileStore) -> None:
        """Test overwriting an existing file"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Overwrite"
        original_content = "Original content"
        new_content = "New content after overwrite"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Save original file
        content_io = BytesIO(original_content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Verify original content
        read_content_io = file_store.read_file(file_id)
        assert read_content_io.read().decode("utf-8") == original_content

        # Overwrite with new content
        new_content_io = BytesIO(new_content.encode("utf-8"))
        returned_file_id_2 = file_store.save_file(
            content=new_content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id_2 == file_id

        # Verify new content
        read_content_io = file_store.read_file(file_id)
        assert read_content_io.read().decode("utf-8") == new_content

    def test_large_file_handling(self, file_store: S3BackedFileStore) -> None:
        """Test handling of larger files"""
        file_id = f"{uuid.uuid4()}.bin"
        display_name = "Test Large File"
        # Create a 1MB file
        content_size = 1024 * 1024  # 1MB
        content = b"A" * content_size
        file_type = "application/octet-stream"
        file_origin = FileOrigin.CONNECTOR

        # Save the large file
        content_io = BytesIO(content)
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Read the file back
        read_content_io = file_store.read_file(file_id)
        read_content = read_content_io.read()

        assert len(read_content) == content_size
        assert read_content == content

    def test_error_handling_nonexistent_file(
        self, file_store: S3BackedFileStore
    ) -> None:
        """Test error handling when trying to read a non-existent file"""
        nonexistent_file_id = f"{uuid.uuid4()}.txt"

        with pytest.raises(RuntimeError, match="does not exist or was deleted"):
            file_store.read_file(nonexistent_file_id)

        with pytest.raises(RuntimeError, match="does not exist or was deleted"):
            file_store.read_file_record(nonexistent_file_id)

        # get_file_with_mime_type should return None for non-existent files
        result = file_store.get_file_with_mime_type(nonexistent_file_id)
        assert result is None

    def test_error_handling_delete_nonexistent_file(
        self, file_store: S3BackedFileStore
    ) -> None:
        """Test error handling when trying to delete a non-existent file"""
        nonexistent_file_id = f"{uuid.uuid4()}.txt"

        # Should raise an exception when trying to delete non-existent file
        with pytest.raises(RuntimeError, match="does not exist or was deleted"):
            file_store.delete_file(nonexistent_file_id)

    def test_multiple_files_different_origins(
        self, file_store: S3BackedFileStore
    ) -> None:
        """Test storing multiple files with different origins and types"""
        files_data: List[FileTestData] = [
            {
                "name": f"{uuid.uuid4()}.txt",
                "display_name": "Chat Upload File",
                "content": "Content from chat upload",
                "type": "text/plain",
                "origin": FileOrigin.CHAT_UPLOAD,
            },
            {
                "name": f"{uuid.uuid4()}.json",
                "display_name": "Connector File",
                "content": '{"from": "connector"}',
                "type": "application/json",
                "origin": FileOrigin.CONNECTOR,
            },
            {
                "name": f"{uuid.uuid4()}.csv",
                "display_name": "Generated Report",
                "content": "col1,col2\nval1,val2",
                "type": "text/csv",
                "origin": FileOrigin.GENERATED_REPORT,
            },
        ]

        # Save all files
        for file_data in files_data:
            content_io = BytesIO(file_data["content"].encode("utf-8"))
            returned_file_id = file_store.save_file(
                content=content_io,
                display_name=file_data["display_name"],
                file_origin=file_data["origin"],
                file_type=file_data["type"],
                file_id=file_data["name"],
            )
            assert returned_file_id == file_data["name"]

        # Verify all files exist and have correct properties
        for file_data in files_data:
            assert file_store.has_file(
                file_id=file_data["name"],
                file_origin=file_data["origin"],
                file_type=file_data["type"],
            )

            # Read and verify content
            read_content_io = file_store.read_file(file_data["name"])
            read_content = read_content_io.read().decode("utf-8")
            assert read_content == file_data["content"]

            # Verify record
            file_record = file_store.read_file_record(file_data["name"])
            assert file_record.file_origin == file_data["origin"]
            assert file_record.file_type == file_data["type"]

    def test_special_characters_in_filenames(
        self, file_store: S3BackedFileStore
    ) -> None:
        """Test handling of special characters in filenames"""
        # Note: S3 keys have some restrictions, so we test reasonable special characters
        special_files: List[str] = [
            f"{uuid.uuid4()} with spaces.txt",
            f"{uuid.uuid4()}-with-dashes.txt",
            f"{uuid.uuid4()}_with_underscores.txt",
            f"{uuid.uuid4()}.with.dots.txt",
            f"{uuid.uuid4()}(with)parentheses.txt",
        ]

        for file_id in special_files:
            content = f"Content for {file_id}"
            content_io = BytesIO(content.encode("utf-8"))

            # Save the file
            returned_file_id = file_store.save_file(
                content=content_io,
                display_name=f"Display: {file_id}",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                file_id=file_id,
            )

            assert returned_file_id == file_id

            # Read and verify
            read_content_io = file_store.read_file(file_id)
            read_content = read_content_io.read().decode("utf-8")
            assert read_content == content

    @pytest.mark.skipif(
        not os.environ.get("TEST_S3_NETWORK_ERRORS"),
        reason="Network error tests require TEST_S3_NETWORK_ERRORS environment variable",
    )
    def test_network_error_handling(self, file_store: S3BackedFileStore) -> None:
        """Test handling of network errors (requires special setup)"""
        # This test requires specific network configuration to simulate failures
        # It's marked as skip by default and only runs when explicitly enabled

        # Mock a network error during file operations
        with patch.object(file_store, "_get_s3_client") as mock_client:
            mock_s3 = mock_client.return_value
            mock_s3.put_object.side_effect = ClientError(
                error_response={
                    "Error": {
                        "Code": "NetworkingError",
                        "Message": "Connection timeout",
                    }
                },
                operation_name="PutObject",
            )

            content_io = BytesIO(b"test content")

            with pytest.raises(ClientError):
                file_store.save_file(
                    content=content_io,
                    display_name="Network Error Test",
                    file_origin=FileOrigin.OTHER,
                    file_type="text/plain",
                    file_id=f"{uuid.uuid4()}.txt",
                )

    def test_database_transaction_rollback(self, file_store: S3BackedFileStore) -> None:
        """Test database transaction rollback behavior with PostgreSQL"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Rollback"
        content = "Content for rollback test"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # Mock S3 to fail after database write but before commit
        with patch.object(file_store, "_get_s3_client") as mock_client:
            mock_s3 = mock_client.return_value
            mock_s3.put_object.side_effect = ClientError(
                error_response={
                    "Error": {"Code": "InternalError", "Message": "S3 internal error"}
                },
                operation_name="PutObject",
            )

            content_io = BytesIO(content.encode("utf-8"))

            # This should fail and rollback the database transaction
            with pytest.raises(ClientError):
                file_store.save_file(
                    content=content_io,
                    display_name=display_name,
                    file_origin=file_origin,
                    file_type=file_type,
                    file_id=file_id,
                )

        # Verify that the database record was not created due to rollback
        with pytest.raises(RuntimeError, match="does not exist or was deleted"):
            file_store.read_file_record(file_id)

    def test_complex_jsonb_metadata(self, file_store: S3BackedFileStore) -> None:
        """Test PostgreSQL JSONB metadata handling with complex data structures"""
        file_id = f"{uuid.uuid4()}.json"
        display_name = "Test Complex Metadata"
        content = '{"data": "test"}'
        file_type = "application/json"
        file_origin = FileOrigin.CONNECTOR

        # Complex metadata that tests PostgreSQL JSONB capabilities
        complex_metadata: Dict[str, Any] = {
            "nested": {
                "array": [1, 2, 3, {"inner": "value"}],
                "boolean": True,
                "null_value": None,
                "number": 42.5,
            },
            "unicode": "测试数据 🚀",
            "special_chars": "Line 1\nLine 2\t\r\nSpecial: !@#$%^&*()",
            "large_text": "x" * 1000,  # Test large text in JSONB
            "timestamps": {
                "created": "2024-01-01T00:00:00Z",
                "updated": "2024-01-02T12:30:45Z",
            },
        }

        # Save file with complex metadata
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=complex_metadata,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Retrieve and verify the metadata was stored correctly
        file_record = file_store.read_file_record(file_id)
        stored_metadata = file_record.file_metadata

        # Verify all metadata fields were preserved
        assert stored_metadata == complex_metadata

        # Type casting for complex metadata access
        stored_metadata_dict = cast(Dict[str, Any], stored_metadata)
        nested_data = cast(Dict[str, Any], stored_metadata_dict["nested"])
        array_data = cast(List[Any], nested_data["array"])
        inner_obj = cast(Dict[str, Any], array_data[3])

        assert inner_obj["inner"] == "value"
        assert stored_metadata_dict["unicode"] == "测试数据 🚀"
        assert nested_data["boolean"] is True
        assert nested_data["null_value"] is None
        assert len(cast(str, stored_metadata_dict["large_text"])) == 1000

    def test_database_consistency_after_s3_failure(
        self, file_store: S3BackedFileStore
    ) -> None:
        """Test that database stays consistent when S3 operations fail"""
        file_id = f"{uuid.uuid4()}.txt"
        display_name = "Test Consistency"
        content = "Initial content"
        file_type = "text/plain"
        file_origin = FileOrigin.OTHER

        # First, save a file successfully
        content_io = BytesIO(content.encode("utf-8"))
        returned_file_id = file_store.save_file(
            content=content_io,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_id=file_id,
        )

        assert returned_file_id == file_id

        # Verify initial state
        assert file_store.has_file(file_id, file_origin, file_type)
        initial_record = file_store.read_file_record(file_id)

        # Now try to update but fail on S3 side
        with patch.object(file_store, "_get_s3_client") as mock_client:
            mock_s3 = mock_client.return_value
            # Let the first call (for reading/checking) succeed, but fail on put_object
            mock_s3.put_object.side_effect = ClientError(
                error_response={
                    "Error": {
                        "Code": "ServiceUnavailable",
                        "Message": "Service temporarily unavailable",
                    }
                },
                operation_name="PutObject",
            )

            new_content = "Updated content that should fail"
            new_content_io = BytesIO(new_content.encode("utf-8"))

            # This should fail and rollback
            with pytest.raises(ClientError):
                file_store.save_file(
                    content=new_content_io,
                    display_name=display_name,
                    file_origin=file_origin,
                    file_type=file_type,
                    file_id=file_id,
                )

        # Verify the database record is unchanged (not updated)
        current_record = file_store.read_file_record(file_id)
        assert current_record.file_id == initial_record.file_id
        assert current_record.display_name == initial_record.display_name
        assert current_record.bucket_name == initial_record.bucket_name
        assert current_record.object_key == initial_record.object_key

        # Verify we can still read the original file content
        read_content_io = file_store.read_file(file_id)
        read_content = read_content_io.read().decode("utf-8")
        assert read_content == content  # Original content, not the failed update

    def test_concurrent_file_operations(self, file_store: S3BackedFileStore) -> None:
        """Test handling of concurrent file operations on the same file"""
        base_file_name: str = str(uuid.uuid4())
        file_type: str = "text/plain"
        file_origin: FileOrigin = FileOrigin.OTHER

        # Get current file store configuration to replicate in workers
        current_bucket_name = file_store._get_bucket_name()
        current_access_key = file_store._aws_access_key_id
        current_secret_key = file_store._aws_secret_access_key
        current_region = file_store._aws_region_name
        current_endpoint_url = file_store._s3_endpoint_url
        current_verify_ssl = file_store._s3_verify_ssl

        results: List[Tuple[str, str]] = []
        errors: List[Tuple[int, str]] = []

        def save_file_worker(worker_id: int) -> bool:
            """Worker function to save a file with its own database session"""
            try:
                # Set up tenant context for this worker
                token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
                try:
                    # Create a new database session for each worker to avoid conflicts
                    with get_session_with_current_tenant() as worker_session:
                        worker_file_store = S3BackedFileStore(
                            bucket_name=current_bucket_name,
                            aws_access_key_id=current_access_key,
                            aws_secret_access_key=current_secret_key,
                            aws_region_name=current_region,
                            s3_endpoint_url=current_endpoint_url,
                            s3_prefix=TEST_FILE_PREFIX,
                            s3_verify_ssl=current_verify_ssl,
                        )

                        file_name: str = f"{base_file_name}_{worker_id}.txt"
                        content: str = (
                            f"Content from worker {worker_id} at {time.time()}"
                        )
                        content_io: BytesIO = BytesIO(content.encode("utf-8"))

                        worker_file_store.save_file(
                            file_id=file_name,
                            content=content_io,
                            display_name=f"Worker {worker_id} File",
                            file_origin=file_origin,
                            file_type=file_type,
                            db_session=worker_session,
                        )
                        results.append((file_name, content))
                        return True
                finally:
                    # Reset the tenant context after the worker completes
                    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
            except Exception as e:
                errors.append((worker_id, str(e)))
                return False

        # Run multiple concurrent file save operations
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(save_file_worker, i) for i in range(10)]

            for future in as_completed(futures):
                future.result()  # Wait for completion

        # Verify all operations completed successfully
        assert len(errors) == 0, f"Concurrent operations had errors: {errors}"
        assert (
            len(results) == 10
        ), f"Expected 10 successful operations, got {len(results)}"

        # Verify all files were saved correctly
        for file_id, expected_content in results:
            # Check file exists
            assert file_store.has_file(
                file_id=file_id,
                file_origin=file_origin,
                file_type=file_type,
            )

            # Check content is correct
            read_content_io = file_store.read_file(file_id)
            actual_content: str = read_content_io.read().decode("utf-8")
            assert actual_content == expected_content

    def test_list_files_by_prefix(self, file_store: S3BackedFileStore) -> None:
        """Test listing files by prefix returns only correctly prefixed files"""
        test_prefix = "documents-batch-"

        # Files that should be returned (start with the prefix)
        prefixed_files: List[str] = [
            f"{test_prefix}001.txt",
            f"{test_prefix}002.json",
            f"{test_prefix}abc.pdf",
            f"{test_prefix}xyz-final.docx",
        ]

        # Files that should NOT be returned (don't start with prefix, even if they contain it)
        non_prefixed_files: List[str] = [
            f"other-{test_prefix}001.txt",  # Contains prefix but doesn't start with it
            f"backup-{test_prefix}data.txt",  # Contains prefix but doesn't start with it
            f"{uuid.uuid4()}.txt",  # Random file without prefix
            "reports-001.pdf",  # Different prefix
            f"my-{test_prefix[:-1]}.txt",  # Similar but not exact prefix
        ]

        all_files = prefixed_files + non_prefixed_files
        saved_file_ids: List[str] = []

        # Save all test files
        for file_name in all_files:
            content = f"Content for {file_name}"
            content_io = BytesIO(content.encode("utf-8"))

            returned_file_id = file_store.save_file(
                content=content_io,
                display_name=f"Display: {file_name}",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                file_id=file_name,
            )
            saved_file_ids.append(returned_file_id)

            # Verify file was saved
            assert returned_file_id == file_name

        # Test the list_files_by_prefix functionality
        prefix_results = file_store.list_files_by_prefix(test_prefix)

        # Extract file IDs from results
        returned_file_ids = [record.file_id for record in prefix_results]

        # Verify correct number of files returned
        assert len(returned_file_ids) == len(prefixed_files), (
            f"Expected {len(prefixed_files)} files with prefix '{test_prefix}', "
            f"but got {len(returned_file_ids)}: {returned_file_ids}"
        )

        # Verify all prefixed files are returned
        for expected_file_id in prefixed_files:
            assert expected_file_id in returned_file_ids, (
                f"File '{expected_file_id}' should be in results but was not found. "
                f"Returned files: {returned_file_ids}"
            )

        # Verify no non-prefixed files are returned
        for unexpected_file_id in non_prefixed_files:
            assert unexpected_file_id not in returned_file_ids, (
                f"File '{unexpected_file_id}' should NOT be in results but was found. "
                f"Returned files: {returned_file_ids}"
            )

        # Verify the returned records have correct properties
        for record in prefix_results:
            assert record.file_id.startswith(test_prefix)
            assert record.display_name == f"Display: {record.file_id}"
            assert record.file_origin == FileOrigin.OTHER
            assert record.file_type == "text/plain"
            assert record.bucket_name == file_store._get_bucket_name()

        # Test with empty prefix (should return all files we created)
        all_results = file_store.list_files_by_prefix("")
        all_returned_ids = [record.file_id for record in all_results]

        # Should include all our test files
        for file_id in saved_file_ids:
            assert (
                file_id in all_returned_ids
            ), f"File '{file_id}' should be in results for empty prefix"

        # Test with non-existent prefix
        nonexistent_results = file_store.list_files_by_prefix("nonexistent-prefix-")
        assert (
            len(nonexistent_results) == 0
        ), "Should return empty list for non-existent prefix"
