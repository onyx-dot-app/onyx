"""Presigned URLs of the S3 file store against a real object store
(S3_ENDPOINT_URL) and, where set, a real legacy MinIO store
(S3_LEGACY_ENDPOINT_URL)."""

import hashlib
import time
import uuid
from collections.abc import Generator
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import (
    FILE_STORE_PRESIGN_MAX_UPLOAD_BYTES,
    S3_ENDPOINT_URL,
    S3_LEGACY_ENDPOINT_URL,
)
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import FileRecord
from onyx.file_store.file_store import (
    LEGACY_OUT_OF_SYNC_PREFIX,
    LEGACY_RETIRED_MARKER_KEY,
    PresignableFileStore,
    PresignedUploadInProgressError,
    PresignedUploadNotFoundError,
    PresignedUploadVerificationError,
    PresignedUrlsNotSupportedError,
    S3BackedFileStore,
    pending_upload_lock_name,
)
from onyx.file_store.legacy_copy import run_pass
from onyx.file_store.models import PresignedRequest, PresignedUpload
from tests.external_dependency_unit.file_store.legacy_store_helpers import (
    BUCKET,
    delete_objects,
    make_store,
    object_exists,
    save,
)

if not S3_ENDPOINT_URL:
    pytest.skip("Needs S3_ENDPOINT_URL", allow_module_level=True)

needs_legacy_store = pytest.mark.skipif(
    not S3_LEGACY_ENDPOINT_URL, reason="Needs S3_LEGACY_ENDPOINT_URL"
)

CONTENT = b"a craft session snapshot"


@pytest.fixture
def store(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[S3BackedFileStore, None, None]:
    assert S3_ENDPOINT_URL
    prefix = f"presign-tests-{uuid.uuid4()}"
    store = make_store(S3_ENDPOINT_URL, None, prefix)
    store.initialize()
    yield store
    delete_objects(store._get_s3_client(), BUCKET, f"{prefix}/")
    db_session.query(FileRecord).filter(
        FileRecord.object_key.startswith(f"{prefix}/")
    ).delete(synchronize_session=False)
    db_session.commit()


def presign(
    store: S3BackedFileStore, content: bytes = CONTENT, ttl: timedelta | None = None
) -> PresignedUpload:
    return store.presign_upload(
        display_name="snapshot.tar",
        file_origin=FileOrigin.OTHER,
        file_type="application/x-tar",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        ttl=ttl,
    )


def send(request: PresignedRequest, content: bytes | None = None) -> httpx.Response:
    return httpx.request(
        request.method, request.url, headers=request.headers, content=content
    )


def has_record(file_id: str) -> bool:
    with get_session_with_current_tenant() as db_session:
        return get_filerecord_by_file_id_optional(file_id, db_session) is not None


def test_an_upload_is_finalized_and_read_back(store: S3BackedFileStore) -> None:
    assert isinstance(store, PresignableFileStore)
    upload = presign(store)
    assert not has_record(upload.file_id)

    assert send(upload.request, CONTENT).status_code == 200
    file_id = store.finalize_presigned_upload(upload.pending_upload_id)

    assert file_id == upload.file_id
    assert store.read_file(file_id).read() == CONTENT
    assert store.read_file_record(file_id).file_size == len(CONTENT)
    with pytest.raises(PresignedUploadNotFoundError):
        store.finalize_presigned_upload(upload.pending_upload_id)


def test_the_upload_url_takes_only_the_expected_bytes(
    store: S3BackedFileStore,
) -> None:
    upload = presign(store)
    same_size = CONTENT[:-1] + b"!"
    other_size = upload.request.model_copy(
        update={
            "headers": {
                k: v for k, v in upload.request.headers.items() if k != "Content-Length"
            }
        }
    )

    assert send(upload.request, same_size).status_code == 400
    assert send(other_size, CONTENT + b"!").status_code == 403
    # Nothing landed, so the pending upload stays for a later finalize.
    with pytest.raises(PresignedUploadVerificationError, match="not been uploaded"):
        store.finalize_presigned_upload(upload.pending_upload_id)

    assert send(upload.request, CONTENT).status_code == 200
    assert store.finalize_presigned_upload(upload.pending_upload_id) == upload.file_id


@pytest.mark.parametrize(
    "landed", [CONTENT + b"!", CONTENT[:-1] + b"!"], ids=["size", "checksum"]
)
def test_finalize_deletes_an_object_that_does_not_match(
    store: S3BackedFileStore, landed: bytes
) -> None:
    upload = presign(store)
    key = store._get_s3_key(upload.file_id)
    # Written around the URL, as a store that skips the checks would.
    store._get_s3_client().put_object(Bucket=BUCKET, Key=key, Body=landed)

    with pytest.raises(PresignedUploadVerificationError):
        store.finalize_presigned_upload(upload.pending_upload_id)

    assert not object_exists(store._get_s3_client(), key)
    assert not has_record(upload.file_id)
    with pytest.raises(PresignedUploadNotFoundError):
        store.finalize_presigned_upload(upload.pending_upload_id)


def test_finalize_runs_once_at_a_time(store: S3BackedFileStore) -> None:
    upload = presign(store)
    assert send(upload.request, CONTENT).status_code == 200
    lock = get_cache_backend().lock(
        pending_upload_lock_name(upload.pending_upload_id), timeout=60
    )
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(PresignedUploadInProgressError):
            store.finalize_presigned_upload(upload.pending_upload_id)
    finally:
        lock.release()

    assert store.finalize_presigned_upload(upload.pending_upload_id) == upload.file_id


def test_a_download_url_reads_the_file(store: S3BackedFileStore) -> None:
    file_id = save(store, CONTENT)

    request = store.presign_download(file_id)

    assert request.method == "GET"
    response = send(request)
    assert response.status_code == 200
    assert response.content == CONTENT


def test_expired_urls_are_refused(store: S3BackedFileStore) -> None:
    upload = presign(store, ttl=timedelta(seconds=1))
    download = store.presign_download(save(store, CONTENT), timedelta(seconds=1))
    time.sleep(2)

    assert send(upload.request, CONTENT).status_code == 403
    assert send(download).status_code == 403


def test_bad_presign_arguments_are_rejected(store: S3BackedFileStore) -> None:
    with pytest.raises(ValueError, match="TTL"):
        presign(store, ttl=timedelta(minutes=16))
    with pytest.raises(ValueError, match="sha256"):
        store.presign_upload(
            display_name=None,
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            size=1,
            sha256="not-a-digest",
        )
    with pytest.raises(ValueError, match="size"):
        store.presign_upload(
            display_name=None,
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            size=FILE_STORE_PRESIGN_MAX_UPLOAD_BYTES + 1,
            sha256="0" * 64,
        )


@needs_legacy_store
def test_the_replay_copies_a_finalized_upload_into_the_legacy_store(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    source, target = old_release._get_s3_client(), new_release._get_s3_client()
    upload = presign(new_release)
    assert send(upload.request, CONTENT).status_code == 200

    file_id = new_release.finalize_presigned_upload(upload.pending_upload_id)

    key = new_release.read_file_record(file_id).object_key
    assert not object_exists(source, key)
    assert object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)
    assert run_pass(source, target, [BUCKET], workers=4).failed == 0
    # A rollback to a release that reads only MinIO finds the file.
    assert old_release.read_file(file_id).read() == CONTENT


@needs_legacy_store
def test_a_retired_legacy_store_gets_no_marker(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
    retired_marker: None,  # noqa: ARG001
) -> None:
    _, new_release = stores
    target = new_release._get_s3_client()
    target.put_object(Bucket=BUCKET, Key=LEGACY_RETIRED_MARKER_KEY, Body=b"retired")
    upload = presign(new_release)
    assert send(upload.request, CONTENT).status_code == 200

    file_id = new_release.finalize_presigned_upload(upload.pending_upload_id)

    key = new_release.read_file_record(file_id).object_key
    assert not object_exists(target, LEGACY_OUT_OF_SYNC_PREFIX + key)


@needs_legacy_store
def test_a_file_only_in_the_legacy_store_gets_no_download_url(
    stores: tuple[S3BackedFileStore, S3BackedFileStore],
) -> None:
    old_release, new_release = stores
    file_id = save(old_release, CONTENT)

    with pytest.raises(PresignedUrlsNotSupportedError):
        new_release.presign_download(file_id)
    assert new_release.read_file(file_id).read() == CONTENT
