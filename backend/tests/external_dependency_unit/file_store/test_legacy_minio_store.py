"""The file store against a real object store and a real legacy MinIO store
(S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL)."""

import os
import uuid
from io import BytesIO
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from onyx.configs.app_configs import S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import (
    LEGACY_OUT_OF_SYNC_PREFIX,
    LEGACY_RETIRED_MARKER_KEY,
    S3BackedFileStore,
    is_missing_object,
)
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.file_store.legacy_store_helpers import (
    BUCKET,
    delete_during_outage,
    object_exists,
    save,
    write_during_outage,
)

if not S3_ENDPOINT_URL or not S3_LEGACY_ENDPOINT_URL:
    pytest.skip(
        "Needs S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL",
        allow_module_level=True,
    )


def test_reads_fall_back_to_the_legacy_store(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"written before the upgrade")

    assert new_release.read_file(file_id).read() == b"written before the upgrade"
    assert new_release.get_file_size(file_id) == len(b"written before the upgrade")


def test_the_object_store_wins_over_the_legacy_store(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"new")
    # The dual write put "new" in both stores, so only MinIO moves on.
    save(old_release, b"stale", file_id)

    assert new_release.read_file(file_id).read() == b"new"


def test_a_rollback_still_reads_files_written_after_the_upgrade(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"written after the upgrade")

    assert old_release.read_file(file_id).read() == b"written after the upgrade"


def test_a_file_in_neither_store_still_raises(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"gone")
    key = new_release.read_file_record(file_id).object_key
    old_release._get_s3_client().delete_object(Bucket=BUCKET, Key=key)

    with pytest.raises(ClientError):
        new_release.read_file(file_id)
    with pytest.raises(FileNotFoundError):
        new_release.get_file_size(file_id)


def test_delete_removes_the_object_from_both_stores(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"delete me")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert object_exists(source, key)
    assert object_exists(target, key)

    new_release.delete_file(file_id)

    assert not object_exists(target, key)
    assert not object_exists(source, key)


def test_delete_removes_the_legacy_object_first(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"delete me")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    outage = ClientError({"Error": {"Code": "500"}}, "DeleteObject")

    # A later copy of MinIO then finds no legacy object to bring back.
    with patch.object(target, "delete_object", side_effect=outage):
        with pytest.raises(ClientError):
            new_release.delete_file(file_id)

    assert not object_exists(source, key)
    assert object_exists(target, key)


def test_dual_writes_create_the_bucket_in_a_fresh_legacy_store(
    fresh_bucket_store: S3BackedFileStore,
) -> None:
    legacy = fresh_bucket_store._get_legacy_s3_client()
    assert legacy is not None

    file_id = save(fresh_bucket_store, b"fresh install")

    key = fresh_bucket_store.read_file_record(file_id).object_key
    bucket = fresh_bucket_store._get_bucket_name()
    assert legacy.get_object(Bucket=bucket, Key=key)["Body"].read() == (
        b"fresh install"
    )


def test_a_write_minio_rejects_lands_in_the_object_store_with_a_marker(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()

    assert new_release.read_file(file_id).read() == b"MinIO was down"
    assert not object_exists(source, key)
    assert object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_a_delete_minio_rejects_still_removes_the_file(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"delete me")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()

    key = delete_during_outage(new_release, file_id)

    assert not object_exists(target, key)
    assert not new_release.has_file(
        file_id, FileOrigin.OTHER, "application/octet-stream"
    )
    # The legacy object stays, and no marker asks for it to be deleted later.
    assert object_exists(source, key)
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_a_miss_before_the_legacy_bucket_exists_reads_as_missing(
    fresh_bucket_store: S3BackedFileStore,
) -> None:
    store = fresh_bucket_store
    file_id, key = write_during_outage(store, b"only in the object store")
    store._get_s3_client().delete_object(Bucket=store._get_bucket_name(), Key=key)

    with pytest.raises(ClientError) as missing:
        store.read_file(file_id)
    assert is_missing_object(missing.value)
    with pytest.raises(FileNotFoundError):
        store.get_file_size(file_id)


def test_a_retired_store_stops_dual_writes_without_a_restart(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retired_marker: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    late = save(old_release, b"written by an older release")
    new_release._get_s3_client().put_object(
        Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
    )

    file_id = save(new_release, b"written after retiring")

    key = new_release.read_file_record(file_id).object_key
    assert not object_exists(old_release._get_s3_client(), key)
    # Reads still fall back while MinIO answers.
    assert new_release.read_file(late).read() == b"written by an older release"


def test_a_miss_reads_as_missing_only_once_minio_is_retired(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retired_marker: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"gone")
    key = new_release.read_file_record(file_id).object_key
    old_release._get_s3_client().delete_object(Bucket=BUCKET, Key=key)
    legacy = new_release._get_legacy_s3_client()
    assert legacy is not None
    down = EndpointConnectionError(endpoint_url="http://minio:9000")

    with patch.object(legacy, "get_object", side_effect=down):
        # During the move a MinIO outage is an outage, not a missing file.
        with pytest.raises(EndpointConnectionError):
            new_release.read_file(file_id)
        new_release._get_s3_client().put_object(
            Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
        )
        with pytest.raises(ClientError) as missing:
            new_release.read_file(file_id)

    assert is_missing_object(missing.value)


def test_craft_snapshots_survive_the_upgrade_and_a_rollback(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    before, after = os.urandom(3 * 1024 * 1024), os.urandom(1024 * 1024)
    tenant_id, sandbox_id = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, str(uuid.uuid4())
    _, snapshot_path, _ = SnapshotManager(old_release).persist_snapshot_from_stream(
        BytesIO(before), sandbox_id, tenant_id
    )
    history_path, _ = SnapshotManager(
        new_release
    ).persist_opencode_snapshot_from_stream(BytesIO(after), sandbox_id, tenant_id)

    restored = BytesIO()
    SnapshotManager(new_release).restore_snapshot_to_stream(snapshot_path, restored)
    assert restored.getvalue() == before
    rolled_back = BytesIO()
    SnapshotManager(old_release).restore_snapshot_to_stream(history_path, rolled_back)
    assert rolled_back.getvalue() == after
