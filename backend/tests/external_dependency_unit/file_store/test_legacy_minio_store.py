"""The file store and the legacy copy against a real object store and a real
legacy MinIO store (S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL)."""

import os
import time
import uuid
from collections.abc import Generator
from datetime import timedelta
from io import BytesIO
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    S3_AWS_ACCESS_KEY_ID,
    S3_AWS_SECRET_ACCESS_KEY,
    S3_ENDPOINT_URL,
    S3_LEGACY_AWS_ACCESS_KEY_ID,
    S3_LEGACY_AWS_SECRET_ACCESS_KEY,
    S3_LEGACY_ENDPOINT_URL,
)
from onyx.configs.constants import FileOrigin
from onyx.file_store import file_store, legacy_copy
from onyx.file_store.file_store import (
    LEGACY_RETIRED_MARKER_KEY,
    S3BackedFileStore,
    is_missing_object,
)
from onyx.file_store.legacy_copy import CopyOutcome, PassStats, copy_object, run_pass
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

if not S3_ENDPOINT_URL or not S3_LEGACY_ENDPOINT_URL:
    pytest.skip(
        "Needs S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL",
        allow_module_level=True,
    )

BUCKET = "onyx-legacy-store-tests"


def _store(
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


def _delete_objects(client: "S3Client", bucket: str, prefix: str = "") -> None:
    listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    for obj in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=obj["Key"])


def _object_exists(client: "S3Client", key: str) -> bool:
    try:
        client.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError as e:
        if is_missing_object(e):
            return False
        raise


@pytest.fixture
def stores(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[S3BackedFileStore, S3BackedFileStore], None, None]:
    """(what an earlier release wrote with, what this release reads with)."""
    assert S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL
    prefix = f"legacy-store-tests-{uuid.uuid4()}"
    old_release = _store(S3_LEGACY_ENDPOINT_URL, None, prefix)
    new_release = _store(S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL, prefix)
    old_release.initialize()
    new_release.initialize()
    yield old_release, new_release
    for client in (old_release._get_s3_client(), new_release._get_s3_client()):
        _delete_objects(client, BUCKET, f"{prefix}/")


def _save(store: S3BackedFileStore, content: bytes, file_id: str | None = None) -> str:
    return store.save_file(
        content=BytesIO(content),
        display_name="legacy.bin",
        file_origin=FileOrigin.OTHER,
        file_type="application/octet-stream",
        file_id=file_id,
    )


def test_reads_fall_back_to_the_legacy_store(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"written before the upgrade")

    assert new_release.read_file(file_id).read() == b"written before the upgrade"
    assert new_release.get_file_size(file_id) == len(b"written before the upgrade")


def test_the_object_store_wins_over_the_legacy_store(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"old")
    _save(new_release, b"new", file_id)

    assert new_release.read_file(file_id).read() == b"new"


def test_a_rollback_still_reads_files_written_after_the_upgrade(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"written after the upgrade")

    assert old_release.read_file(file_id).read() == b"written after the upgrade"


def test_a_file_in_neither_store_still_raises(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"gone")
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
    file_id = _save(old_release, b"delete me")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED

    new_release.delete_file(file_id)

    assert not _object_exists(target, key)
    assert not _object_exists(source, key)


def test_delete_removes_the_legacy_object_first(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"delete me")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    outage = ClientError({"Error": {"Code": "500"}}, "DeleteObject")

    # A copy racing the delete then finds no legacy object to keep its copy for.
    with patch.object(target, "delete_object", side_effect=outage):
        with pytest.raises(ClientError):
            new_release.delete_file(file_id)

    assert not _object_exists(source, key)
    assert _object_exists(target, key)


def test_copy_moves_every_object_and_keeps_newer_ones(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    copied_ids = [_save(old_release, f"file {i}".encode()) for i in range(5)]
    newer_id = _save(old_release, b"stale")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    _save(new_release, b"written after the upgrade", newer_id)

    stats = run_pass(source, target, [BUCKET], workers=4)

    assert stats.failed == 0
    assert stats.copied >= len(copied_ids)
    for i, file_id in enumerate(copied_ids):
        key = new_release.read_file_record(file_id).object_key
        body = target.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        assert body == f"file {i}".encode()
    assert new_release.read_file(newer_id).read() == b"written after the upgrade"
    assert run_pass(source, target, [BUCKET], workers=4).copied == 0


def test_copy_never_overwrites_a_write_that_lands_after_its_check(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"stale")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    target.put_object(Bucket=BUCKET, Key=key, Body=b"fresh")
    missing = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    # The head check sees nothing, as if the app wrote right after it.
    with patch.object(target, "head_object", side_effect=missing):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.PRESENT
    assert target.get_object(Bucket=BUCKET, Key=key)["Body"].read() == b"fresh"


def _source_head_at(
    source: "S3Client", target: "S3Client", key: str, seconds_after_target: int
) -> dict[str, Any]:
    target_modified = target.head_object(Bucket=BUCKET, Key=key)["LastModified"]
    return {
        **source.head_object(Bucket=BUCKET, Key=key),
        "LastModified": target_modified + timedelta(seconds=seconds_after_target),
    }


def test_copy_refreshes_an_object_an_older_release_rewrote(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"before the rollback")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    # A rolled-back release rewrites the key in the legacy store only.
    source.put_object(Bucket=BUCKET, Key=key, Body=b"during the rollback")
    later = _source_head_at(source, target, key, seconds_after_target=1)

    with patch.object(source, "head_object", return_value=later):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.COPIED
    assert new_release.read_file(file_id).read() == b"during the rollback"


def test_copy_keeps_the_app_write_on_a_timestamp_tie(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"written by the app")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    source.put_object(Bucket=BUCKET, Key=key, Body=b"written by an older release")
    same_second = _source_head_at(source, target, key, seconds_after_target=0)

    with patch.object(source, "head_object", return_value=same_second):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.PRESENT
    assert new_release.read_file(file_id).read() == b"written by the app"


def test_copy_keeps_a_target_that_changes_after_its_check(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"before the rollback")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    stale_head = target.head_object(Bucket=BUCKET, Key=key)
    source.put_object(Bucket=BUCKET, Key=key, Body=b"during the rollback")
    later = _source_head_at(source, target, key, seconds_after_target=1)
    target.put_object(Bucket=BUCKET, Key=key, Body=b"written by the app")

    # The head check sees the target as it was before the app's write.
    with (
        patch.object(target, "head_object", return_value=stale_head),
        patch.object(source, "head_object", return_value=later),
    ):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.PRESENT
    assert (
        target.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        == b"written by the app"
    )


def test_copy_refreshes_a_source_rewritten_while_it_was_copied(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"read by the copy")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_complete = target.complete_multipart_upload

    def complete_after_rewrite(**kwargs: Any) -> Any:
        # An older release rewrites the key between the copy's read and its put,
        # so the copy is newer than the rewrite (timestamps have 1s resolution).
        source.put_object(Bucket=BUCKET, Key=key, Body=b"rewritten during the copy")
        time.sleep(1.1)
        return real_complete(**kwargs)

    with patch.object(
        target, "complete_multipart_upload", side_effect=complete_after_rewrite
    ):
        assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED

    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED
    assert new_release.read_file(file_id).read() == b"rewritten during the copy"


def test_copy_never_replaces_a_write_with_a_late_dual_write(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"second save")
    key = new_release.read_file_record(file_id).object_key
    # The legacy half of an earlier save of the same key lands last.
    new_release._put_legacy_object(
        BUCKET, key, b"first save", "application/octet-stream", {}
    )
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    later = _source_head_at(source, target, key, seconds_after_target=1)

    with patch.object(source, "head_object", return_value=later):
        assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.PRESENT
    assert new_release.read_file(file_id).read() == b"second save"


def test_copy_repairs_a_target_it_overwrote_before_a_dual_write(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"older release")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    # The copy lands between a save's object store half and its legacy half.
    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED
    new_release._put_legacy_object(
        BUCKET, key, b"this release", "application/octet-stream", {}
    )

    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED
    assert new_release.read_file(file_id).read() == b"this release"


def test_copy_retries_a_source_that_changes_after_its_check(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(new_release, b"before the rollback")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    source.put_object(Bucket=BUCKET, Key=key, Body=b"checked")
    checked = _source_head_at(source, target, key, seconds_after_target=1)
    real_get = source.get_object

    def get_after_rewrite(**kwargs: Any) -> Any:
        source.put_object(Bucket=BUCKET, Key=key, Body=b"rewritten after the check")
        return real_get(**kwargs)

    with (
        patch.object(source, "head_object", return_value=checked),
        patch.object(source, "get_object", side_effect=get_after_rewrite),
    ):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.RETRY
    assert new_release.read_file(file_id).read() == b"before the rollback"


def test_a_watch_pass_copies_only_what_changed(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_ids = [_save(old_release, f"file {i}".encode()) for i in range(3)]
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert run_pass(source, target, [BUCKET], workers=4).failed == 0
    newest = max(
        obj["LastModified"] for obj in source.list_objects_v2(Bucket=BUCKET)["Contents"]
    )
    time.sleep(1.1)
    key = new_release.read_file_record(file_ids[0]).object_key
    source.put_object(Bucket=BUCKET, Key=key, Body=b"written during a rollback")

    watched = run_pass(
        source,
        target,
        [BUCKET],
        workers=4,
        modified_since=newest + timedelta(seconds=1),
    )

    assert (watched.listed, watched.copied) == (1, 1)
    assert new_release.read_file(file_ids[0]).read() == b"written during a rollback"


def test_copy_does_not_bring_back_a_file_deleted_during_the_copy(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"deleted during the copy")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_complete = target.complete_multipart_upload

    def complete_after_delete(**kwargs: Any) -> Any:
        new_release.delete_file(file_id)
        return real_complete(**kwargs)

    with patch.object(
        target, "complete_multipart_upload", side_effect=complete_after_delete
    ):
        outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.VANISHED
    assert not _object_exists(target, key)


def test_copy_keeps_a_file_saved_again_after_a_delete_during_the_copy(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"same bytes")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_get, real_head = source.get_object, source.head_object

    def get_then_delete(**kwargs: Any) -> Any:
        read = real_get(**kwargs)
        new_release.delete_file(file_id)
        return read

    def save_again_then_head(**kwargs: Any) -> Any:
        # The app saves the same bytes again after the copy's put, before its
        # legacy half lands.
        target.put_object(Bucket=BUCKET, Key=key, Body=b"same bytes")
        return real_head(**kwargs)

    with (
        patch.object(source, "get_object", side_effect=get_then_delete),
        patch.object(source, "head_object", side_effect=save_again_then_head),
    ):
        copy_object(source, target, BUCKET, key)

    assert target.get_object(Bucket=BUCKET, Key=key)["Body"].read() == b"same bytes"


def test_dual_writes_create_the_bucket_in_a_fresh_legacy_store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> None:
    assert S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL
    bucket = f"legacy-fresh-{uuid.uuid4()}"
    store = _store(S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL, "fresh", bucket)
    store.initialize()
    legacy = store._get_legacy_s3_client()
    assert legacy is not None
    try:
        file_id = _save(store, b"fresh install")
        key = store.read_file_record(file_id).object_key
        assert legacy.get_object(Bucket=bucket, Key=key)["Body"].read() == (
            b"fresh install"
        )
    finally:
        for client in (store._get_s3_client(), legacy):
            try:
                _delete_objects(client, bucket)
            except ClientError:
                continue
            client.delete_bucket(Bucket=bucket)


@pytest.fixture
def retirable(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> Generator[MagicMock, None, None]:
    """Checks the retire marker on every call and points the copy at BUCKET.
    Yields the patched bucket listing."""
    target = stores[1]._get_s3_client()
    with (
        patch.object(file_store, "LEGACY_RETIRED_RECHECK_SECONDS", 0),
        patch.object(legacy_copy, "_RETIRE_QUIET_SECONDS", 0),
        patch.object(legacy_copy, "S3_FILE_STORE_BUCKET_NAME", BUCKET),
        patch.object(legacy_copy, "LEGACY_COPY_SETTLE_SECONDS", 0),
        patch.object(
            legacy_copy, "_list_and_ensure_buckets", return_value=[BUCKET]
        ) as list_buckets,
    ):
        yield list_buckets
    target.delete_object(Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY)
    file_store._legacy_retired.clear()


def test_retire_copies_everything_then_writes_the_marker(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"only in the legacy store")
    key = new_release.read_file_record(file_id).object_key
    real_run_pass = legacy_copy.run_pass
    passes: list[PassStats] = []

    def changed_then_real(*args: Any, **kwargs: Any) -> PassStats:
        # The first pass saw a source change mid-copy, so retiring runs another.
        stats = (
            PassStats(listed=1, retry=1)
            if not passes
            else real_run_pass(*args, **kwargs)
        )
        passes.append(stats)
        return stats

    with patch.object(legacy_copy, "run_pass", side_effect=changed_then_real):
        legacy_copy.retire_legacy_store()

    target = new_release._get_s3_client()
    assert _object_exists(target, key)
    assert _object_exists(target, LEGACY_RETIRED_MARKER_KEY)


def test_retire_refuses_while_an_older_release_still_writes(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    written: list[str] = []

    def older_release_writes(_seconds: float) -> None:
        written.append(_save(old_release, b"written by a pod on the older release"))

    with patch.object(legacy_copy.time, "sleep", side_effect=older_release_writes):
        with pytest.raises(RuntimeError, match="MinIO stays in use"):
            legacy_copy.retire_legacy_store()

    target = new_release._get_s3_client()
    assert not _object_exists(target, LEGACY_RETIRED_MARKER_KEY)
    key = new_release.read_file_record(written[0]).object_key
    assert _object_exists(target, key)


def test_a_retired_store_stops_dual_writes_without_a_restart(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    late = _save(old_release, b"written by an older release")
    new_release._get_s3_client().put_object(
        Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
    )

    file_id = _save(new_release, b"written after retiring")

    key = new_release.read_file_record(file_id).object_key
    assert not _object_exists(old_release._get_s3_client(), key)
    # Reads still fall back while MinIO answers, until the copy reaches the file.
    assert new_release.read_file(late).read() == b"written by an older release"


def test_a_miss_reads_as_missing_only_once_minio_is_retired(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"gone")
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


def test_the_copy_stops_once_the_store_is_retired(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: None,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = _save(old_release, b"left in the legacy store")
    key = new_release.read_file_record(file_id).object_key
    target = new_release._get_s3_client()
    target.put_object(Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired")

    legacy_copy.copy_legacy_objects()

    assert not _object_exists(target, key)


def test_the_watch_copies_late_writes_until_a_retired_store_stops(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,
) -> None:
    old_release, new_release = stores
    target = new_release._get_s3_client()
    late: list[str] = []
    down = ClientError({"Error": {"Code": "503"}}, "ListBuckets")
    sleeps = 0

    def before_each_pass(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            target.put_object(
                Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
            )
            # A pod still on an older release writes after retirement.
            late.append(_save(old_release, b"written after retiring"))
        elif sleeps == 2:
            retirable.side_effect = down
        elif sleeps == 3:
            # MinIO comes back from a blip, and the watch carries on.
            retirable.side_effect = None
            late.append(_save(old_release, b"written after the blip"))
        elif sleeps == 4:
            retirable.side_effect = down
        elif sleeps > 6:
            raise AssertionError("the watch kept running after MinIO stopped")

    with patch.object(legacy_copy.time, "sleep", side_effect=before_each_pass):
        legacy_copy.copy_legacy_objects(watch=True)

    assert sleeps == 6
    for file_id in late:
        key = new_release.read_file_record(file_id).object_key
        assert _object_exists(target, key)


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
