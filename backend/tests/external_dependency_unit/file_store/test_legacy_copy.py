"""The legacy copy against a real object store and a real legacy MinIO store
(S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL)."""

import itertools
import time
import uuid
from collections.abc import Generator
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from onyx.configs.app_configs import S3_ENDPOINT_URL, S3_LEGACY_ENDPOINT_URL
from onyx.file_store import legacy_copy
from onyx.file_store.file_store import (
    LEGACY_OUT_OF_SYNC_PREFIX,
    LEGACY_RETIRED_MARKER_KEY,
    S3BackedFileStore,
)
from onyx.file_store.legacy_copy import (
    CopyOutcome,
    PassStats,
    _list_and_ensure_buckets,
    copy_object,
    run_pass,
)
from tests.external_dependency_unit.file_store.legacy_store_helpers import (
    BUCKET,
    delete_during_outage,
    delete_objects,
    object_exists,
    save,
    write_during_outage,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

if not S3_ENDPOINT_URL or not S3_LEGACY_ENDPOINT_URL:
    pytest.skip(
        "Needs S3_ENDPOINT_URL and S3_LEGACY_ENDPOINT_URL",
        allow_module_level=True,
    )


def test_delete_removes_a_copied_object_from_both_stores(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"delete me")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED

    new_release.delete_file(file_id)

    assert not object_exists(target, key)
    assert not object_exists(source, key)


def test_copy_moves_every_object_and_keeps_newer_ones(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    copied_ids = [save(old_release, f"file {i}".encode()) for i in range(5)]
    newer_id = save(old_release, b"stale")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    save(new_release, b"written after the upgrade", newer_id)

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
    file_id = save(old_release, b"stale")
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
    file_id = save(new_release, b"before the rollback")
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
    file_id = save(new_release, b"written by the app")
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
    file_id = save(new_release, b"before the rollback")
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
    file_id = save(old_release, b"read by the copy")
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
    file_id = save(new_release, b"second save")
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
    file_id = save(old_release, b"older release")
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
    file_id = save(new_release, b"before the rollback")
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


def test_copy_does_not_bring_back_a_file_deleted_during_the_copy(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"deleted during the copy")
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
    assert not object_exists(target, key)


def test_copy_keeps_a_file_saved_again_after_a_delete_during_the_copy(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"same bytes")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_get, real_delete = source.get_object, target.delete_object

    def get_then_delete(**kwargs: Any) -> Any:
        read = real_get(**kwargs)
        new_release.delete_file(file_id)
        return read

    def save_again_then_delete(**kwargs: Any) -> Any:
        # The app saves the same bytes again between the copy's record check
        # and its cleanup delete.
        if kwargs["Key"] == key:
            save(new_release, b"same bytes", file_id)
        return real_delete(**kwargs)

    with (
        patch.object(source, "get_object", side_effect=get_then_delete),
        patch.object(target, "delete_object", side_effect=save_again_then_delete),
    ):
        copy_object(source, target, BUCKET, key)

    assert target.get_object(Bucket=BUCKET, Key=key)["Body"].read() == b"same bytes"


def test_a_failed_legacy_write_is_resynced(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)

    assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    # A rollback to a release that reads only MinIO finds the file.
    assert old_release.read_file(file_id).read() == b"MinIO was down"
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_a_replay_keeps_a_write_that_lands_during_it(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_put = source.put_object
    saved = False

    def save_again_then_put(**kwargs: Any) -> Any:
        nonlocal saved
        if not saved:
            saved = True
            save(new_release, b"saved while the replay ran", file_id)
        return real_put(**kwargs)

    with patch.object(source, "put_object", side_effect=save_again_then_put):
        assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    assert old_release.read_file(file_id).read() == b"saved while the replay ran"
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_a_failed_legacy_delete_is_never_copied_back(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"deleted while MinIO was down")
    key = delete_during_outage(new_release, file_id)
    source, target = old_release._get_s3_client(), new_release._get_s3_client()

    for _ in range(2):
        stats = run_pass(source, target, [BUCKET], workers=4)
        assert (stats.failed, stats.unreferenced) == (0, 1)

    # MinIO keeps its stale copy, which no file record points at.
    assert object_exists(source, key)
    assert not object_exists(target, key)


def test_a_copied_file_deleted_during_an_outage_stays_deleted(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"from before the upgrade")
    key = new_release.read_file_record(file_id).object_key
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    assert copy_object(source, target, BUCKET, key)[0] == CopyOutcome.COPIED
    delete_during_outage(new_release, file_id)

    for _ in range(2):
        assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    assert object_exists(source, key)
    assert not object_exists(target, key)


def test_a_rewrite_after_a_failed_delete_is_copied(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"deleted while MinIO was down")
    delete_during_outage(new_release, file_id)
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    # A rolled-back release saves the same file again, in MinIO only, within
    # the same second and possibly with the same bytes.
    save(old_release, b"deleted while MinIO was down", file_id)

    for _ in range(3):
        assert run_pass(source, target, [BUCKET], workers=4).failed == 0
        assert new_release.read_file(file_id).read() == b"deleted while MinIO was down"


def test_copy_removes_its_copy_when_the_record_is_gone(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"deleted while MinIO was down")
    key = delete_during_outage(new_release, file_id)
    source, target = old_release._get_s3_client(), new_release._get_s3_client()

    # A copy that listed the key before the delete finds no record after its put.
    outcome, _ = copy_object(source, target, BUCKET, key)

    assert outcome == CopyOutcome.VANISHED
    assert not object_exists(target, key)


def test_copy_skips_objects_without_a_file_record(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    key = f"{old_release._s3_prefix}/public/no-record"
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    source.put_object(Bucket=BUCKET, Key=key, Body=b"nothing points here")

    stats = run_pass(source, target, [BUCKET], workers=4)

    assert (stats.copied, stats.unreferenced) == (0, 1)
    assert not object_exists(target, key)


def test_a_pass_aborts_the_uploads_a_killed_copy_left(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    prefix = new_release._s3_prefix
    target.create_multipart_upload(Bucket=BUCKET, Key=f"{prefix}/public/died-mid-put")

    run_pass(source, target, [BUCKET], workers=4)

    uploads = target.list_multipart_uploads(Bucket=BUCKET, Prefix=prefix)
    assert uploads.get("Uploads", []) == []


def test_a_pass_stops_once_a_store_stops_answering(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    for i in range(legacy_copy._MAX_CONSECUTIVE_FAILURES + 8):
        save(old_release, f"file {i}".encode())
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    down = EndpointConnectionError(endpoint_url="http://minio:9000")

    with patch.object(legacy_copy, "copy_object", side_effect=down):
        with pytest.raises(RuntimeError, match="in a row"):
            run_pass(source, target, [BUCKET], workers=4)


def test_scattered_failures_do_not_stop_a_pass(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    for i in range(2 * legacy_copy._MAX_CONSECUTIVE_FAILURES + 4):
        save(old_release, f"file {i}".encode())
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    real_copy = legacy_copy.copy_object
    calls = itertools.count()

    def every_other_fails(*args: Any, **kwargs: Any) -> Any:
        if next(calls) % 2:
            raise EndpointConnectionError(endpoint_url="http://minio:9000")
        return real_copy(*args, **kwargs)

    with patch.object(legacy_copy, "copy_object", side_effect=every_other_fails):
        stats = run_pass(source, target, [BUCKET], workers=1)

    assert stats.failed >= legacy_copy._MAX_CONSECUTIVE_FAILURES


def test_a_write_marker_yields_to_a_later_write_of_an_older_release(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    time.sleep(1.1)
    # A rolled-back release saves the file again, in MinIO only.
    save(old_release, b"written after the rollback", file_id)

    assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    assert new_release.read_file(file_id).read() == b"written after the rollback"
    assert old_release.read_file(file_id).read() == b"written after the rollback"
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_a_write_marker_for_a_deleted_file_is_dropped(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down")
    new_release.delete_file(file_id)
    source, target = old_release._get_s3_client(), new_release._get_s3_client()

    assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)
    assert not object_exists(source, key)


def test_a_key_that_stays_out_of_sync_counts_as_failed(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    _, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    outage = ClientError({"Error": {"Code": "503"}}, "PutObject")

    # MinIO still refuses the write when the copy replays it.
    with patch.object(source, "put_object", side_effect=outage):
        stats = run_pass(source, target, [BUCKET], workers=4)

    assert stats.failed == 1
    assert not object_exists(source, key)
    assert object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_resync_mirrors_a_file_saved_again_after_its_failed_delete(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(new_release, b"first save")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    legacy = new_release._get_legacy_s3_client()
    assert legacy is not None
    outage = ClientError({"Error": {"Code": "503"}}, "Unavailable")
    with (
        patch.object(legacy, "delete_object", side_effect=outage),
        patch.object(legacy, "put_object", side_effect=outage),
    ):
        new_release.delete_file(file_id)
        save(new_release, b"saved again", file_id)

    assert run_pass(source, target, [BUCKET], workers=4).failed == 0

    assert old_release.read_file(file_id).read() == b"saved again"


@pytest.fixture
def retirable(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retired_marker: None,  # noqa: ARG001
) -> Generator[MagicMock, None, None]:
    """Points the copy at BUCKET with no waits. Yields the patched bucket listing."""
    source, target = stores[0]._get_s3_client(), stores[1]._get_s3_client()
    with (
        patch.object(legacy_copy, "_clients", return_value=(source, target)),
        patch.object(legacy_copy, "_RETIRE_QUIET_SECONDS", 0),
        patch.object(legacy_copy, "_PASS_INTERVAL_SECONDS", 0),
        patch.object(legacy_copy, "S3_FILE_STORE_BUCKET_NAME", BUCKET),
        patch.object(legacy_copy, "LEGACY_COPY_SETTLE_SECONDS", 0),
        patch.object(
            legacy_copy, "_list_and_ensure_buckets", return_value=[BUCKET]
        ) as list_buckets,
    ):
        yield list_buckets


def test_retire_copies_everything_then_writes_the_marker(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"only in the legacy store")
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
    assert object_exists(target, key)
    assert object_exists(target, LEGACY_RETIRED_MARKER_KEY)


def test_retire_refuses_while_an_older_release_still_writes(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    written: list[str] = []

    def older_release_writes(_seconds: float) -> None:
        written.append(save(old_release, b"written by a pod on the older release"))

    with patch.object(legacy_copy.time, "sleep", side_effect=older_release_writes):
        with pytest.raises(RuntimeError, match="MinIO stays in use"):
            legacy_copy.retire_legacy_store()

    target = new_release._get_s3_client()
    assert not object_exists(target, LEGACY_RETIRED_MARKER_KEY)
    key = new_release.read_file_record(written[0]).object_key
    assert object_exists(target, key)


def test_replay_covers_a_bucket_created_while_minio_was_down(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,
) -> None:
    old_release, new_release = stores
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    bucket = f"onyx-legacy-replay-{uuid.uuid4().hex[:8]}"
    key = f"{new_release._s3_prefix}/public/new-bucket-file"
    target.create_bucket(Bucket=bucket)
    target.put_object(Bucket=bucket, Key=key, Body=b"written while MinIO was down")
    target.put_object(Bucket=bucket, Key=LEGACY_OUT_OF_SYNC_PREFIX + key, Body=b"x")
    retirable.side_effect = _list_and_ensure_buckets
    sleeps = 0

    def retire_on_the_second_pass(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            target.put_object(
                Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
            )

    try:
        with patch.object(
            legacy_copy.time, "sleep", side_effect=retire_on_the_second_pass
        ):
            legacy_copy.replay_legacy_writes()

        mirrored = source.get_object(Bucket=bucket, Key=key)["Body"].read()
        assert mirrored == b"written while MinIO was down"
    finally:
        for client in (source, target):
            delete_objects(client, bucket)
            client.delete_bucket(Bucket=bucket)


def test_replay_mirrors_a_write_that_failed_after_the_copy(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id, key = write_during_outage(new_release, b"MinIO was down after the copy")
    target = new_release._get_s3_client()
    sleeps = 0

    def retire_on_the_second_pass(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            target.put_object(
                Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired"
            )
        elif sleeps > 2:
            raise AssertionError("the replay kept running after MinIO was retired")

    with patch.object(legacy_copy.time, "sleep", side_effect=retire_on_the_second_pass):
        legacy_copy.replay_legacy_writes()

    assert sleeps == 2
    assert old_release.read_file(file_id).read() == b"MinIO was down after the copy"
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_retire_refuses_while_a_key_stays_out_of_sync(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    _, key = write_during_outage(new_release, b"MinIO was down")
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    outage = ClientError({"Error": {"Code": "503"}}, "PutObject")

    with patch.object(source, "put_object", side_effect=outage):
        with pytest.raises(RuntimeError, match="stays in use"):
            legacy_copy.retire_legacy_store()

    assert not object_exists(target, LEGACY_RETIRED_MARKER_KEY)
    assert object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


def test_the_copy_completes_once_a_pass_finds_nothing_new(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"left in the legacy store")
    key = new_release.read_file_record(file_id).object_key
    real_run_pass = legacy_copy.run_pass
    passes: list[PassStats] = []

    def counted(*args: Any, **kwargs: Any) -> PassStats:
        passes.append(real_run_pass(*args, **kwargs))
        return passes[-1]

    with patch.object(legacy_copy, "run_pass", side_effect=counted):
        legacy_copy.copy_legacy_objects()

    assert object_exists(new_release._get_s3_client(), key)
    # The pass that copied the file is followed by one that finds nothing new.
    assert [stats.copied for stats in passes] == [1, 0]


def test_the_copy_stops_once_the_store_is_retired(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retirable: MagicMock,  # noqa: ARG001
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, b"left in the legacy store")
    key = new_release.read_file_record(file_id).object_key
    target = new_release._get_s3_client()
    target.put_object(Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired")

    legacy_copy.copy_legacy_objects()

    assert not object_exists(target, key)
