"""Blob storage pruning lists object keys and downloads nothing.

A prune deletes every indexed document whose ID the listing does not return.
These tests run the real prune listing against the object store (MinIO) and
check that it returns the same IDs indexing produces, without one download.
"""

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import boto3
import pytest

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.app_configs import (
    S3_AWS_ACCESS_KEY_ID,
    S3_AWS_SECRET_ACCESS_KEY,
    S3_ENDPOINT_URL,
)
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.models import Document
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

# Indexing stores each file's record, so it needs the DB and the file store.
pytestmark = [
    pytest.mark.skipif(
        not S3_ENDPOINT_URL, reason="needs an S3-compatible object store"
    ),
    pytest.mark.usefixtures("db_session", "tenant_context", "initialize_file_store"),
]

SIZE_THRESHOLD = 1024
PREFIX = "docs/"
INDEXABLE_KEYS = ["docs/a.txt", "docs/sub/b.md", "docs/sub/deeper/c.txt"]
SKIPPED_KEYS = [
    "docs/picture.png",  # image, images not allowed
    "docs/too-big.txt",  # over the size threshold
    "other/outside.txt",  # outside the prefix
]


class _StopHeartbeat(IndexingHeartbeatInterface):
    def should_stop(self) -> bool:
        return True

    def progress(self, tag: str, amount: int) -> None:  # noqa: ARG002
        return None


@pytest.fixture
def s3_client() -> "S3Client":
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY,
        region_name="us-east-1",
    )


@pytest.fixture
def bucket(s3_client: "S3Client") -> Generator[str, None, None]:
    name = f"blob-slim-prune-{uuid4().hex[:12]}"
    s3_client.create_bucket(Bucket=name)
    for key in INDEXABLE_KEYS + ["docs/picture.png", "other/outside.txt"]:
        s3_client.put_object(Bucket=name, Key=key, Body=f"content of {key}".encode())
    s3_client.put_object(
        Bucket=name, Key="docs/too-big.txt", Body=b"x" * (SIZE_THRESHOLD + 1)
    )
    s3_client.put_object(Bucket=name, Key="docs/folder/", Body=b"")
    yield name
    for obj in s3_client.list_objects_v2(Bucket=name).get("Contents", []):
        s3_client.delete_object(Bucket=name, Key=obj["Key"])
    s3_client.delete_bucket(Bucket=name)


@pytest.fixture
def connector(s3_client: "S3Client", bucket: str) -> BlobStorageConnector:
    connector = BlobStorageConnector(
        bucket_type="s3", bucket_name=bucket, prefix=PREFIX
    )
    connector.s3_client = s3_client
    connector.size_threshold = SIZE_THRESHOLD
    connector.set_allow_images(False)
    return connector


def _indexed_ids(connector: BlobStorageConnector) -> set[str]:
    return {
        doc.id
        for batch in connector.load_from_state()
        for doc in batch
        if isinstance(doc, Document)
    }


def test_prune_listing_matches_indexing_without_downloads(
    connector: BlobStorageConnector, bucket: str
) -> None:
    indexed = _indexed_ids(connector)
    assert indexed == {f"BlobType.S3:{bucket}:{key}" for key in INDEXABLE_KEYS}

    with patch.object(
        BlobStorageConnector,
        "_download_object",
        side_effect=AssertionError("pruning must not download objects"),
    ):
        result = extract_ids_from_runnable_connector(connector, callback=None)

    assert set(result.raw_id_to_parent) == indexed
    assert not {f"BlobType.S3:{bucket}:{key}" for key in SKIPPED_KEYS} & set(
        result.raw_id_to_parent
    )


def test_prune_keeps_objects_that_fail_to_download(
    connector: BlobStorageConnector, bucket: str
) -> None:
    """Indexing skips an object it cannot read; pruning must still list it, so
    one failed read never deletes an indexed document."""
    failing_key = INDEXABLE_KEYS[0]
    real_download = BlobStorageConnector._download_object

    def _download(self: BlobStorageConnector, key: str) -> bytes | None:
        if key == failing_key:
            raise ConnectionError("read timed out")
        return real_download(self, key)

    with patch.object(BlobStorageConnector, "_download_object", _download):
        assert f"BlobType.S3:{bucket}:{failing_key}" not in _indexed_ids(connector)
        result = extract_ids_from_runnable_connector(connector, callback=None)

    assert f"BlobType.S3:{bucket}:{failing_key}" in result.raw_id_to_parent


def test_stop_signal_aborts_the_listing(connector: BlobStorageConnector) -> None:
    """A partial listing would read as deleted objects, so it must raise."""
    with pytest.raises(RuntimeError, match="stop signal"):
        list(connector.retrieve_all_slim_docs(callback=_StopHeartbeat()))
