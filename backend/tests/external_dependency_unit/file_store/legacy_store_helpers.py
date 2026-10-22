"""Helpers for the legacy MinIO store tests and the legacy copy tests."""

from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import patch

from botocore.exceptions import ClientError

from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    S3_AWS_ACCESS_KEY_ID,
    S3_AWS_SECRET_ACCESS_KEY,
    S3_LEGACY_AWS_ACCESS_KEY_ID,
    S3_LEGACY_AWS_SECRET_ACCESS_KEY,
)
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import S3BackedFileStore, is_missing_object

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BUCKET = "onyx-legacy-store-tests"


def make_store(
    endpoint: str, legacy_endpoint: str | None, prefix: str, bucket: str = BUCKET
) -> S3BackedFileStore:
    return S3BackedFileStore(
        bucket_name=bucket,
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY,
        aws_region_name=AWS_REGION_NAME,
        s3_endpoint_url=endpoint,
        s3_prefix=prefix,
        s3_verify_ssl=False,
        legacy_endpoint_url=legacy_endpoint,
        legacy_access_key_id=S3_LEGACY_AWS_ACCESS_KEY_ID,
        legacy_secret_access_key=S3_LEGACY_AWS_SECRET_ACCESS_KEY,
    )


def delete_objects(client: "S3Client", bucket: str, prefix: str = "") -> None:
    listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    for obj in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=obj["Key"])


def save(store: S3BackedFileStore, content: bytes, file_id: str | None = None) -> str:
    return store.save_file(
        content=BytesIO(content),
        display_name="legacy.bin",
        file_origin=FileOrigin.OTHER,
        file_type="application/octet-stream",
        file_id=file_id,
    )


def delete_during_outage(store: S3BackedFileStore, file_id: str) -> str:
    """Deletes a file while MinIO refuses deletes. Returns its key."""
    key = store.read_file_record(file_id).object_key
    legacy = store._get_legacy_s3_client()
    assert legacy is not None
    outage = ClientError({"Error": {"Code": "503"}}, "DeleteObject")
    with patch.object(legacy, "delete_object", side_effect=outage):
        store.delete_file(file_id)
    return key


def write_during_outage(store: S3BackedFileStore, content: bytes) -> tuple[str, str]:
    """Saves a file while MinIO refuses writes. Returns its id and key."""
    legacy = store._get_legacy_s3_client()
    assert legacy is not None
    outage = ClientError({"Error": {"Code": "503"}}, "PutObject")
    with patch.object(legacy, "put_object", side_effect=outage):
        file_id = save(store, content)
    return file_id, store.read_file_record(file_id).object_key


def object_exists(client: "S3Client", key: str) -> bool:
    try:
        client.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError as e:
        if is_missing_object(e):
            return False
        raise
