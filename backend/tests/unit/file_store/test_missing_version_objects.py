"""Only confirmed object absence can remove a retained version's file link."""

from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import ResourceNotFoundError
from botocore.exceptions import ClientError
from google.api_core.exceptions import Forbidden, NotFound

from onyx.db.models import SkillVersion
from onyx.db.skill_version import repair_version_metadata
from onyx.file_store import azure_blob_file_store as azure
from onyx.file_store import file_store as storage
from onyx.file_store import gcs_file_store as gcs
from onyx.file_store.file_store import FileStore
from onyx.skills.bundle import STORED_BUNDLE_LIMITS


def cloud_store(
    monkeypatch: pytest.MonkeyPatch, backend: str, failure: str
) -> FileStore:
    client = MagicMock()
    blob = MagicMock()
    if backend == "azure":
        store = azure.AzureBlobBackedFileStore(
            account_name="test", container_name="test"
        )
        error = ResourceNotFoundError("missing resource")
        # Azure's storage SDK sets this field after constructing the exception.
        monkeypatch.setattr(
            error,
            "error_code",
            {"object": "BlobNotFound", "bucket": "ContainerNotFound"}.get(failure),
            raising=False,
        )
        client.get_blob_client.return_value = blob
        blob.download_blob.side_effect = error
        blob.get_blob_properties.side_effect = error
        monkeypatch.setattr(store, "_get_blob_service_client", lambda: client)
        module = azure
    elif backend == "gcs":
        store = gcs.GCSBackedFileStore.__new__(gcs.GCSBackedFileStore)
        client.bucket.return_value.blob.return_value = blob
        blob.download_as_bytes.side_effect = NotFound("missing resource")
        blob.reload.side_effect = NotFound("missing resource")
        if failure != "object":
            client.bucket.return_value.reload.side_effect = (
                Forbidden("bucket inaccessible")
                if failure == "unknown"
                else NotFound("bucket missing")
            )
        monkeypatch.setattr(store, "_get_gcs_client", lambda: client)
        module = gcs
    else:
        store = storage.S3BackedFileStore("test")
        error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        client.head_object.side_effect = error
        client.get_object.side_effect = ClientError(
            {
                "Error": {
                    "Code": {
                        "object": "NoSuchKey",
                        "bucket": "NoSuchBucket",
                        "unknown": "404",
                    }[failure]
                }
            },
            "GetObject",
        )
        if failure != "object":
            client.head_bucket.side_effect = ClientError(
                {"Error": {"Code": "403" if failure == "unknown" else "404"}},
                "HeadBucket",
            )
        monkeypatch.setattr(store, "_get_s3_client", lambda: client)
        monkeypatch.setattr(store, "_get_legacy_s3_client", lambda: None)
        module = storage
    monkeypatch.setattr(
        module, "get_filerecord_by_file_id", lambda **_kwargs: MagicMock()
    )
    monkeypatch.setattr(
        module, "get_session_with_current_tenant_if_none", lambda _session: MagicMock()
    )
    return store


@pytest.mark.parametrize("backend", ["azure", "gcs", "s3"])
@pytest.mark.parametrize("failure", ["object", "bucket", "unknown"])
def test_size_distinguishes_missing_object_from_unavailable_storage(
    monkeypatch: pytest.MonkeyPatch, backend: str, failure: str
) -> None:
    store = cloud_store(monkeypatch, backend, failure)
    if failure == "object":
        with pytest.raises(FileNotFoundError):
            store.get_file_size("bundle")
    else:
        assert store.get_file_size("bundle") is None


@pytest.mark.parametrize("backend", ["azure", "gcs", "s3"])
@pytest.mark.parametrize("failure", ["object", "bucket", "unknown"])
@pytest.mark.parametrize("complete", [False, True])
def test_repair_preserves_links_without_missing_object_evidence(
    monkeypatch: pytest.MonkeyPatch, backend: str, failure: str, complete: bool
) -> None:
    store = cloud_store(monkeypatch, backend, failure)
    version = SkillVersion(bundle_file_id="bundle")
    if complete:
        "digest"
        version.unpacked_size_bytes = 20
        version.file_count = 1
        version.frontmatter = {"name": "bundle"}
    if failure == "object" or complete:
        assert not repair_version_metadata(
            version, store, limits=STORED_BUNDLE_LIMITS, clear_missing_bundle=True
        )
    else:
        with pytest.raises((ResourceNotFoundError, NotFound, ClientError)):
            repair_version_metadata(
                version, store, limits=STORED_BUNDLE_LIMITS, clear_missing_bundle=True
            )
    assert version.bundle_file_id == (None if failure == "object" else "bundle")


@pytest.mark.parametrize(
    "bucket_error", ["404", "NotFound", "NoSuchBucket", "403", "500"]
)
def test_missing_primary_object_with_legacy_bucket_error(
    monkeypatch: pytest.MonkeyPatch, bucket_error: str
) -> None:
    store = cloud_store(monkeypatch, "s3", "object")
    legacy = MagicMock()
    legacy.head_object.side_effect = ClientError(
        {"Error": {"Code": "404"}}, "HeadObject"
    )
    legacy.head_bucket.side_effect = ClientError(
        {"Error": {"Code": bucket_error}}, "HeadBucket"
    )
    monkeypatch.setattr(store, "_get_legacy_s3_client", lambda: legacy)
    version = SkillVersion(
        bundle_file_id="bundle",
        unpacked_size_bytes=20,
        file_count=1,
        frontmatter={"name": "bundle"},
    )
    assert not repair_version_metadata(
        version, store, limits=STORED_BUNDLE_LIMITS, clear_missing_bundle=True
    )
    missing = bucket_error in ("404", "NotFound", "NoSuchBucket")
    assert version.bundle_file_id == (None if missing else "bundle")
    legacy.get_object.assert_not_called()
