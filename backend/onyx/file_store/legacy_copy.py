"""Copy every object from the legacy MinIO store into the bundled object store.

Runs beside the app, which falls back to the legacy store on a miss, so the copy
never blocks traffic. Conditional puts let a file the app writes during the copy
win. Each pass first replays into the legacy store the keys a failed app write or
delete marked.

Usage: python -m onyx.file_store.legacy_copy [--watch | --retire]
"""

import argparse
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import partial
from typing import IO, TYPE_CHECKING, TypedDict

from botocore.exceptions import ClientError

from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    LEGACY_COPY_SETTLE_SECONDS,
    LEGACY_COPY_WORKERS,
    S3_AWS_ACCESS_KEY_ID,
    S3_AWS_SECRET_ACCESS_KEY,
    S3_ENDPOINT_URL,
    S3_FILE_STORE_BUCKET_NAME,
    S3_LEGACY_AWS_ACCESS_KEY_ID,
    S3_LEGACY_AWS_SECRET_ACCESS_KEY,
    S3_LEGACY_ENDPOINT_URL,
    S3_VERIFY_SSL,
)
from onyx.file_store.file_store import (
    DUAL_WRITE_METADATA_KEY,
    LEGACY_OUT_OF_SYNC_ACTION_KEY,
    LEGACY_OUT_OF_SYNC_PREFIX,
    LEGACY_RETIRED_MARKER_KEY,
    build_s3_client,
    ensure_bucket,
    is_missing_object,
    legacy_store_retired,
    s3_error_code,
)
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
        GetObjectOutputTypeDef,
        HeadObjectOutputTypeDef,
        ObjectTypeDef,
    )

logger = setup_logger()

# Objects up to this size are buffered in memory, larger ones on local disk.
_SPOOL_MAX_BYTES = 16 * 1024 * 1024
_CHUNK_BYTES = 8 * 1024 * 1024
_PASS_INTERVAL_SECONDS = 60
_WATCH_INTERVAL_SECONDS = 300
# Each watch pass also covers this long before the previous pass started, for
# uploads that were in flight then and for clock skew between the stores.
_WATCH_OVERLAP = timedelta(minutes=10)
# A release before the object store writes to MinIO alone, and a pass after this
# long without such a write shows that none still runs.
_RETIRE_QUIET_SECONDS = 60
# A retired MinIO that misses this many watch passes in a row has been stopped.
_RETIRED_STOP_AFTER_FAILED_PASSES = 3
# Records which legacy version each copy came from.
_COPIED_FROM_METADATA_KEY = "onyx-legacy-etag"


class _Condition(TypedDict, total=False):
    IfMatch: str
    IfNoneMatch: str


class CopyOutcome(str, Enum):
    COPIED = "copied"
    PRESENT = "present"
    # Deleted from the legacy store after it was listed.
    VANISHED = "vanished"
    # Changed in the legacy store during the copy, so the next pass decides.
    RETRY = "retry"
    FAILED = "failed"


@dataclass
class PassStats:
    listed: int = 0
    copied: int = 0
    present: int = 0
    vanished: int = 0
    retry: int = 0
    failed: int = 0
    copied_bytes: int = 0

    def add(self, outcome: CopyOutcome, size: int) -> None:
        self.listed += 1
        if outcome == CopyOutcome.COPIED:
            self.copied += 1
            self.copied_bytes += size
        elif outcome == CopyOutcome.PRESENT:
            self.present += 1
        elif outcome == CopyOutcome.VANISHED:
            self.vanished += 1
        elif outcome == CopyOutcome.RETRY:
            self.retry += 1
        else:
            self.failed += 1


def _content_type(obj: "GetObjectOutputTypeDef") -> str:
    return obj.get("ContentType") or "application/octet-stream"


@contextmanager
def _spooled_body(obj: "GetObjectOutputTypeDef") -> Iterator[tuple[IO[bytes], int]]:
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES) as buffer:
        for chunk in obj["Body"].iter_chunks(chunk_size=_CHUNK_BYTES):
            buffer.write(chunk)
        size = buffer.tell()
        buffer.seek(0)
        yield buffer, size


def _head(
    client: "S3Client", bucket: str, key: str
) -> "HeadObjectOutputTypeDef | None":
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if is_missing_object(e):
            return None
        raise


def _needs_refresh(
    source_head: "HeadObjectOutputTypeDef", target_head: "HeadObjectOutputTypeDef"
) -> bool:
    if source_head["ETag"] == target_head["ETag"]:
        return False
    # The copy wrote the target, so a legacy version it did not copy is newer.
    copied_from = target_head["Metadata"].get(_COPIED_FROM_METADATA_KEY)
    if copied_from is not None:
        return source_head["ETag"] != copied_from
    if DUAL_WRITE_METADATA_KEY in source_head["Metadata"]:
        return False
    # An unmarked source newer than an app write came from a rollback. A tie
    # means two releases wrote the key in one second, and the app's write stays.
    return source_head["LastModified"] > target_head["LastModified"]


# A one-part multipart upload gets an ETag that no plain upload of the same bytes
# has, so the cleanup delete in copy_object never matches a later app write.
def _put_new_object(
    target: "S3Client",
    bucket: str,
    key: str,
    body: IO[bytes],
    content_type: str,
    metadata: dict[str, str],
) -> str:
    upload_id = target.create_multipart_upload(
        Bucket=bucket, Key=key, ContentType=content_type, Metadata=metadata
    )["UploadId"]
    try:
        part = target.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=1, Body=body
        )
        return target.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": [{"ETag": part["ETag"], "PartNumber": 1}]},
            IfNoneMatch="*",
        )["ETag"]
    except Exception:
        try:
            target.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        except Exception:
            logger.warning("Failed to abort the upload of %s/%s", bucket, key)
        raise


def copy_object(
    source: "S3Client", target: "S3Client", bucket: str, key: str
) -> tuple[CopyOutcome, int]:
    get_condition: _Condition = {}
    target_head = _head(target, bucket, key)
    if target_head is not None:
        source_head = _head(source, bucket, key)
        if source_head is None or not _needs_refresh(source_head, target_head):
            return CopyOutcome.PRESENT, 0
        get_condition = {"IfMatch": source_head["ETag"]}

    try:
        obj = source.get_object(Bucket=bucket, Key=key, **get_condition)
    except ClientError as e:
        if is_missing_object(e):
            return CopyOutcome.VANISHED, 0
        if s3_error_code(e) == "PreconditionFailed":
            return CopyOutcome.RETRY, 0
        raise

    content_type = _content_type(obj)
    metadata = {_COPIED_FROM_METADATA_KEY: obj["ETag"]}
    # Set only for a new object, the case that can outlive a racing delete.
    written_etag: str | None = None
    with _spooled_body(obj) as (buffer, size):
        try:
            if target_head is None:
                written_etag = _put_new_object(
                    target, bucket, key, buffer, content_type, metadata
                )
            else:
                target.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=buffer,
                    ContentType=content_type,
                    Metadata=metadata,
                    IfMatch=target_head["ETag"],
                )
        except ClientError as e:
            # The app wrote or deleted this key after the head check above.
            if s3_error_code(e) == "PreconditionFailed":
                return CopyOutcome.PRESENT, 0
            raise

    # The app deletes from both stores, and a delete between the read and the
    # put above would leave this copy behind with no file record. The If-Match
    # keeps a file the app wrote again since.
    if written_etag is not None and _head(source, bucket, key) is None:
        try:
            target.delete_object(Bucket=bucket, Key=key, IfMatch=written_etag)
        except ClientError as e:
            if s3_error_code(e) != "PreconditionFailed" and not is_missing_object(e):
                raise
        return CopyOutcome.VANISHED, 0
    return CopyOutcome.COPIED, size


def _copy_object_logged(
    source: "S3Client", target: "S3Client", bucket: str, key: str
) -> tuple[CopyOutcome, int]:
    try:
        return copy_object(source, target, bucket, key)
    except Exception:
        logger.exception("Failed to copy %s/%s", bucket, key)
        return CopyOutcome.FAILED, 0


def _resync_key(
    source: "S3Client",
    target: "S3Client",
    bucket: str,
    key: str,
    marker: "ObjectTypeDef",
) -> str | None:
    """Returns the marker's action."""
    action = target.head_object(Bucket=bucket, Key=marker["Key"])["Metadata"].get(
        LEGACY_OUT_OF_SYNC_ACTION_KEY
    )
    if action == "delete":
        # The MinIO copy stays, held back from the forward copy by the marker.
        # A copy that raced the delete left an orphan, which its metadata shows.
        target_head = _head(target, bucket, key)
        if (
            target_head is not None
            and _COPIED_FROM_METADATA_KEY in target_head["Metadata"]
        ):
            target.delete_object(Bucket=bucket, Key=key, IfMatch=target_head["ETag"])
        return action
    source_head = _head(source, bucket, key)
    # A legacy object newer than the marker came from an older release writing
    # it again, and the forward copy takes it.
    if source_head is not None and source_head["LastModified"] > marker["LastModified"]:
        return action
    obj: "GetObjectOutputTypeDef | None" = None
    try:
        obj = target.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if not is_missing_object(e):
            raise
    if obj is None:
        # Deleted since, and that delete's legacy half went through.
        return action
    with _spooled_body(obj) as (buffer, _):
        # The dual-write mark stops the forward copy from treating this as a
        # newer legacy version.
        source.put_object(
            Bucket=bucket,
            Key=key,
            Body=buffer,
            ContentType=_content_type(obj),
            Metadata={DUAL_WRITE_METADATA_KEY: "1"},
        )
    return action


def _resync_out_of_sync(
    source: "S3Client", target: "S3Client", bucket: str
) -> tuple[dict[str, datetime], int]:
    """Make the legacy store match the object store for every key that a failed
    app write or delete marked. A delete marker stays as a tombstone, and the
    forward copy skips MinIO objects no newer than it. Returns the tombstones
    and the number of keys still out of sync."""
    tombstones: dict[str, datetime] = {}
    failed = 0
    paginator = target.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=LEGACY_OUT_OF_SYNC_PREFIX):
        for marker in page.get("Contents", []):
            key = marker["Key"].removeprefix(LEGACY_OUT_OF_SYNC_PREFIX)
            try:
                if _resync_key(source, target, bucket, key, marker) == "delete":
                    tombstones[key] = marker["LastModified"]
                    continue
                target.delete_object(
                    Bucket=bucket, Key=marker["Key"], IfMatch=marker["ETag"]
                )
            except Exception:
                logger.warning(
                    "Failed to resync %s/%s with the legacy MinIO store",
                    bucket,
                    key,
                    exc_info=True,
                )
                # Held back until it is resynced, whatever its age.
                tombstones[key] = datetime.max.replace(tzinfo=timezone.utc)
                failed += 1
    return tombstones, failed


# MinIO lists with milliseconds and SeaweedFS with seconds, so a same-second
# write and tombstone compare equal, and the tombstone wins.
def _held_back(obj: "ObjectTypeDef", tombstones: dict[str, datetime]) -> bool:
    tombstone = tombstones.get(obj["Key"])
    if tombstone is None:
        return False
    return obj["LastModified"].replace(microsecond=0) <= tombstone.replace(
        microsecond=0
    )


def run_pass(
    source: "S3Client",
    target: "S3Client",
    buckets: list[str],
    workers: int,
    modified_since: datetime | None = None,
) -> PassStats:
    """Copy the objects of the given buckets, or only those modified since the
    given time."""
    stats = PassStats()
    paginator = source.get_paginator("list_objects_v2")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for bucket in buckets:
            # Runs before the listing, so a key that a failed delete left in
            # MinIO is held back, never copied back.
            tombstones, failed = _resync_out_of_sync(source, target, bucket)
            stats.failed += failed
            copy_key = partial(_copy_object_logged, source, target, bucket)
            for page in paginator.paginate(Bucket=bucket):
                keys = [
                    obj["Key"]
                    for obj in page.get("Contents", [])
                    if not _held_back(obj, tombstones)
                    and (
                        modified_since is None or obj["LastModified"] >= modified_since
                    )
                ]
                if not keys:
                    continue
                for outcome, size in pool.map(copy_key, keys):
                    stats.add(outcome, size)
                logger.info(
                    "Legacy copy pass so far (at %s): %d listed, %d copied (%d MiB), "
                    "%d present, %d vanished, %d to retry, %d failed",
                    bucket,
                    stats.listed,
                    stats.copied,
                    stats.copied_bytes // (1024 * 1024),
                    stats.present,
                    stats.vanished,
                    stats.retry,
                    stats.failed,
                )
    return stats


def _list_and_ensure_buckets(
    source: "S3Client", target: "S3Client", ensured: set[str]
) -> list[str]:
    buckets = [bucket["Name"] for bucket in source.list_buckets()["Buckets"]]
    for bucket in set(buckets) - ensured:
        ensure_bucket(target, bucket)
        ensured.add(bucket)
    return buckets


def _clients() -> tuple["S3Client", "S3Client"]:
    """(legacy MinIO, object store)."""
    assert S3_LEGACY_ENDPOINT_URL
    source = build_s3_client(
        S3_LEGACY_ENDPOINT_URL,
        S3_LEGACY_AWS_ACCESS_KEY_ID,
        S3_LEGACY_AWS_SECRET_ACCESS_KEY,
        AWS_REGION_NAME,
        S3_VERIFY_SSL,
    )
    target = build_s3_client(
        S3_ENDPOINT_URL,
        S3_AWS_ACCESS_KEY_ID,
        S3_AWS_SECRET_ACCESS_KEY,
        AWS_REGION_NAME,
        S3_VERIFY_SSL,
    )
    return source, target


def _retired(target: "S3Client") -> bool:
    return legacy_store_retired(target, S3_ENDPOINT_URL, S3_FILE_STORE_BUCKET_NAME)


def copy_legacy_objects(watch: bool = False) -> None:
    """Copy until a pass finds nothing new after the settle window. Raises
    RuntimeError when objects fail to copy, so the job exits non-zero. With
    watch, it then copies what changes and retries failures instead of raising,
    until the legacy store is retired and stops answering."""
    if not S3_LEGACY_ENDPOINT_URL:
        logger.info("No legacy MinIO store to copy from.")
        return
    source, target = _clients()
    if _retired(target):
        logger.info("The legacy MinIO store is retired, so there is nothing to copy.")
        return

    started = time.monotonic()
    ensured: set[str] = set()
    while True:
        # A pass can run for hours, so the watch starts from when it began.
        since = datetime.now(timezone.utc)
        buckets = _list_and_ensure_buckets(source, target, ensured)
        stats = run_pass(source, target, buckets, LEGACY_COPY_WORKERS)
        if stats.failed:
            raise RuntimeError(
                f"{stats.failed} objects failed to copy from the legacy MinIO store"
            )
        settled = time.monotonic() - started >= LEGACY_COPY_SETTLE_SECONDS
        if stats.copied == 0 and stats.retry == 0 and settled:
            logger.info(
                "Legacy MinIO copy complete: all %d objects in %s are in the object store.",
                stats.listed,
                ", ".join(buckets) or "no buckets",
            )
            break
        time.sleep(_PASS_INTERVAL_SECONDS)
    if not watch:
        return

    # After a rollback an older release writes to MinIO only, and a container
    # that outlives the rollback copies what it writes. After retirement it
    # keeps copying late writes of an older release until MinIO is stopped.
    failed_passes = 0
    while True:
        time.sleep(_WATCH_INTERVAL_SECONDS)
        retired = _retired(target)
        started_at = datetime.now(timezone.utc)
        try:
            buckets = _list_and_ensure_buckets(source, target, ensured)
            stats = run_pass(
                source, target, buckets, LEGACY_COPY_WORKERS, since - _WATCH_OVERLAP
            )
        except Exception:
            failed_passes += 1
            if retired and failed_passes >= _RETIRED_STOP_AFTER_FAILED_PASSES:
                logger.info(
                    "The legacy MinIO store is retired and has not answered for "
                    "%d passes, so the watch stops.",
                    failed_passes,
                )
                return
            logger.exception("Legacy MinIO watch pass failed, retrying")
            continue
        failed_passes = 0
        # Failed objects stay in the window, so the next pass tries them again.
        if stats.failed == 0:
            since = started_at


def _copy_until_clean(
    source: "S3Client", target: "S3Client", ensured: set[str]
) -> PassStats:
    while True:
        buckets = _list_and_ensure_buckets(source, target, ensured)
        stats = run_pass(source, target, buckets, LEGACY_COPY_WORKERS)
        if stats.failed:
            raise RuntimeError(
                f"{stats.failed} objects failed to copy, so the legacy MinIO store stays in use"
            )
        if stats.copied == 0 and stats.retry == 0:
            return stats


def retire_legacy_store() -> None:
    """Copy until a pass finds nothing new, check that no older release still
    writes to the legacy store, then write the marker that stops every process
    from writing to it. Raises RuntimeError, without the marker, if one does."""
    if not S3_LEGACY_ENDPOINT_URL:
        logger.info("No legacy MinIO store to retire.")
        return
    source, target = _clients()
    ensured: set[str] = set()
    _copy_until_clean(source, target, ensured)
    time.sleep(_RETIRE_QUIET_SECONDS)
    stats = run_pass(
        source,
        target,
        _list_and_ensure_buckets(source, target, ensured),
        LEGACY_COPY_WORKERS,
    )
    if stats.copied or stats.retry or stats.failed:
        raise RuntimeError(
            "Files still reach the legacy MinIO store alone, so a release before "
            "the object store may be running. MinIO stays in use. Retire it once "
            "those pods are gone."
        )
    ensure_bucket(target, S3_FILE_STORE_BUCKET_NAME)
    # An empty PUT stalled the next request on its connection in testing.
    target.put_object(
        Bucket=S3_FILE_STORE_BUCKET_NAME,
        Key=LEGACY_RETIRED_MARKER_KEY,
        Body=f"retired {datetime.now(timezone.utc).isoformat()}".encode(),
    )
    logger.info(
        "Retired the legacy MinIO store after checking %d objects. Running "
        "processes stop writing to it within a minute, and MinIO can be stopped.",
        stats.listed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--watch", action="store_true", help="keep copying after the copy completes"
    )
    mode.add_argument(
        "--retire",
        action="store_true",
        help="finish the copy, then stop every process from using MinIO",
    )
    args = parser.parse_args()
    if args.retire:
        retire_legacy_store()
    else:
        copy_legacy_objects(watch=args.watch)
