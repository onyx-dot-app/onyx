"""
Tests for PersistentDocumentWriter (local) and S3PersistentDocumentWriter.

Run with:
    python -m dotenv -f .vscode/.env run -- \
        pytest backend/tests/external_dependency_unit/craft/test_persistent_document_writer.py -v
"""

import json
import os
import tempfile
from datetime import datetime
from datetime import timezone
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.indexing.persistent_document_writer import (
    PersistentDocumentWriter,
)
from onyx.server.features.build.indexing.persistent_document_writer import (
    S3PersistentDocumentWriter,
)
from tests.external_dependency_unit.constants import TEST_TENANT_ID


def _create_test_document(doc_id: str, name: str) -> Document:
    """Helper to create a test document."""
    return Document(
        id=doc_id,
        semantic_identifier=name,
        title=name,
        source=DocumentSource.WEB,
        sections=[TextSection(text="Test content", link="https://example.com")],
        metadata={},
        doc_metadata={"hierarchy": {"source_path": ["Folder"]}},
        doc_updated_at=datetime.now(timezone.utc),
        primary_owners=[],
        secondary_owners=[],
    )


def test_local_persistent_document_writer() -> None:
    """Test writing documents to local filesystem."""
    with tempfile.TemporaryDirectory() as temp_dir:
        tenant_id = TEST_TENANT_ID
        user_id = str(uuid4())
        writer = PersistentDocumentWriter(
            base_path=temp_dir, tenant_id=tenant_id, user_id=user_id
        )

        doc = _create_test_document("doc-001", "Test Document")
        written_paths = writer.write_documents([doc])

        assert len(written_paths) == 1
        assert written_paths[0] == os.path.join(
            temp_dir,
            tenant_id,
            "knowledge",
            user_id,
            "web",
            "Folder",
            "Test_Document.json",
        )
        assert os.path.exists(written_paths[0])

        with open(written_paths[0]) as f:
            content = json.load(f)
        assert content["id"] == "doc-001"
        assert content["semantic_identifier"] == "Test Document"


def _is_s3_available() -> bool:
    """Check if S3 is available for testing."""
    try:
        s3_client = boto3.client("s3")
        s3_client.head_bucket(Bucket=SANDBOX_S3_BUCKET)
        return True
    except (ClientError, Exception):
        return False


@pytest.mark.skipif(
    not _is_s3_available(),
    reason=f"S3 bucket '{SANDBOX_S3_BUCKET}' not available",
)
def test_s3_persistent_document_writer() -> None:
    """Test writing documents to S3."""
    user_id = str(uuid4())
    writer = S3PersistentDocumentWriter(tenant_id=TEST_TENANT_ID, user_id=user_id)

    doc = _create_test_document("s3-doc-001", "S3 Test Doc")
    written_keys = writer.write_documents([doc])

    try:
        assert len(written_keys) == 1
        assert f"{TEST_TENANT_ID}/knowledge/{user_id}" in written_keys[0]

        # Verify the object exists in S3
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=SANDBOX_S3_BUCKET, Key=written_keys[0])
        content = json.loads(response["Body"].read().decode("utf-8"))

        assert content["id"] == "s3-doc-001"
        assert content["semantic_identifier"] == "S3 Test Doc"
    finally:
        # Cleanup
        s3_client = boto3.client("s3")
        try:
            s3_client.delete_object(Bucket=SANDBOX_S3_BUCKET, Key=written_keys[0])
        except Exception:
            pass
