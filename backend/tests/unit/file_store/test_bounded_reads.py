import io
import tempfile
import zipfile
from pathlib import Path
from typing import IO
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError
from botocore.response import StreamingBody
from google.api_core.exceptions import RequestRangeNotSatisfiable

from onyx.file_processing.zip_stream import ZipMemberReader
from onyx.file_store import azure_blob_file_store as azure
from onyx.file_store import file_store as storage
from onyx.file_store import gcs_file_store as gcs
from onyx.file_store import postgres_file_store as postgres
from onyx.file_store.models import BundleLimits
from onyx.utils.bundle import compute_bundle_metadata


@pytest.mark.parametrize("backend", ["s3", "postgres"])
@pytest.mark.parametrize("failure", ["size", "read", "write", "success"])
@pytest.mark.parametrize("use_tempfile", [False, True])
def test_backend_read_closes_resources(
    monkeypatch: pytest.MonkeyPatch, backend: str, failure: str, use_tempfile: bool
) -> None:
    requests: list[int] = []

    class Source(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None and size > 0
            requests.append(size)
            if failure == "read":
                raise ConnectionError("read failed")
            return super().read(size)

    source = Source(b"x" * 100)

    targets: list[IO[bytes]] = []
    temp_paths: list[Path] = []
    make_tempfile = tempfile.NamedTemporaryFile

    def target(**_kwargs: object) -> IO[bytes]:
        result = (
            make_tempfile(mode="w+b", delete=True) if use_tempfile else io.BytesIO()
        )
        targets.append(result)
        if use_tempfile:
            temp_paths.append(Path(str(result.name)))
        if failure == "write":
            result.close()
        return result

    monkeypatch.setattr(storage.tempfile, "NamedTemporaryFile", target)
    monkeypatch.setattr(storage, "BytesIO", target)
    if backend == "s3":
        store = storage.S3BackedFileStore("test")
        body = StreamingBody(source, 100)
        monkeypatch.setattr(
            store, "_with_legacy_fallback", lambda _operation: {"Body": body}
        )
        monkeypatch.setattr(
            storage, "get_filerecord_by_file_id", lambda **_kwargs: MagicMock()
        )
        monkeypatch.setattr(
            storage,
            "get_session_with_current_tenant_if_none",
            lambda _session: MagicMock(),
        )
    else:
        store = postgres.PostgresBackedFileStore()
        lobj = MagicMock(read=source.read, close=source.close)
        connection = MagicMock()
        connection.lobject.return_value = lobj
        monkeypatch.setattr(
            postgres, "_get_raw_connection", lambda _session: connection
        )
        monkeypatch.setattr(
            postgres, "get_file_content_by_file_id", lambda **_kwargs: MagicMock()
        )
        monkeypatch.setattr(
            postgres,
            "get_session_with_current_tenant_if_none",
            lambda _session: MagicMock(),
        )
    allowance = 99 if failure == "size" else 100
    if failure == "success":
        with store.read_file(
            "file", use_tempfile=use_tempfile, max_bytes=allowance
        ) as result:
            assert result.read() == b"x" * 100
    else:
        error = ConnectionError if failure == "read" else ValueError
        with pytest.raises(error):
            store.read_file("file", use_tempfile=use_tempfile, max_bytes=allowance)
    assert source.closed
    assert targets and all(result.closed for result in targets)
    assert all(not path.exists() for path in temp_paths)
    assert requests and all(0 < size <= allowance + 1 for size in requests)


@pytest.mark.parametrize("backend", ["gcs", "azure"])
@pytest.mark.parametrize("size", [0, 5, 6, 1000000])
@pytest.mark.parametrize("use_tempfile", [False, True])
def test_cloud_range_is_bounded_before_materialization(
    monkeypatch: pytest.MonkeyPatch, backend: str, size: int, use_tempfile: bool
) -> None:
    blob = MagicMock()
    content = b"x" * size
    if backend == "gcs":
        store = gcs.GCSBackedFileStore.__new__(gcs.GCSBackedFileStore)
        client = MagicMock()
        client.bucket.return_value.blob.return_value = blob
        monkeypatch.setattr(store, "_get_gcs_client", lambda: client)
        blob.download_as_bytes.side_effect = lambda **kwargs: content[
            kwargs["start"] : kwargs["end"] + 1
        ]
        monkeypatch.setattr(
            gcs, "get_filerecord_by_file_id", lambda **_kwargs: MagicMock()
        )
        monkeypatch.setattr(
            gcs, "get_session_with_current_tenant_if_none", lambda _session: MagicMock()
        )
    else:
        store = azure.AzureBlobBackedFileStore.__new__(azure.AzureBlobBackedFileStore)
        client = MagicMock()
        client.get_blob_client.return_value = blob
        monkeypatch.setattr(store, "_get_blob_service_client", lambda: client)
        blob.download_blob.side_effect = lambda **kwargs: io.BytesIO(
            content[kwargs["offset"] : kwargs["length"]]
        )
        monkeypatch.setattr(
            azure, "get_filerecord_by_file_id", lambda **_kwargs: MagicMock()
        )
        monkeypatch.setattr(
            azure,
            "get_session_with_current_tenant_if_none",
            lambda _session: MagicMock(),
        )
    if size > 5:
        with pytest.raises(storage.FileSizeLimitExceeded):
            store.read_file("file", max_bytes=5, use_tempfile=use_tempfile)
    else:
        with store.read_file("file", max_bytes=5, use_tempfile=use_tempfile) as source:
            assert source.read() == content
    if backend == "gcs":
        blob.download_as_bytes.assert_called_once_with(
            start=0, end=5, raw_download=True
        )
    else:
        blob.download_blob.assert_called_once_with(offset=0, length=6)
    # An empty object can reject a ranged GET. Other range failures must propagate.
    for empty in [True, False]:
        if backend == "gcs":
            blob.download_as_bytes.side_effect = RequestRangeNotSatisfiable("range")
            blob.size = None

            def reload_size(is_empty: bool = empty) -> None:
                blob.size = 0 if is_empty else 1

            blob.reload.side_effect = reload_size
        else:
            error = HttpResponseError("range")
            error.status_code = 416
            blob.download_blob.side_effect = error
            blob.get_blob_properties.return_value.size = 0 if empty else 1
        if empty:
            with store.read_file("file", max_bytes=5) as source:
                assert source.read() == b""
        else:
            with pytest.raises((RequestRangeNotSatisfiable, HttpResponseError)):
                store.read_file("file", max_bytes=5)


@pytest.mark.parametrize(
    "compression",
    [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA],
)
@pytest.mark.parametrize("total", [False, True])
def test_expansion_stops_on_actual_bytes_and_closes_entries(
    monkeypatch: pytest.MonkeyPatch, total: bool, compression: int
) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as archive:
        archive.writestr("a", b"x" * 100000)
        archive.writestr("b", b"y" * 100000)
    consumed = 0
    sources: list[ZipMemberReader] = []
    read = ZipMemberReader.read

    def measured(source: ZipMemberReader, n: int | None = -1) -> bytes:
        nonlocal consumed
        assert n is not None and 0 < n <= 65536
        sources.append(source)
        chunk = read(source, n)
        consumed += len(chunk)
        return chunk

    monkeypatch.setattr(ZipMemberReader, "read", measured)
    limits = BundleLimits(
        max_stored_bytes=100000,
        max_file_bytes=100000 if total else 99999,
        max_total_bytes=150000,
    )
    with pytest.raises(storage.FileSizeLimitExceeded):
        compute_bundle_metadata(output.getvalue(), limits=limits)
    assert consumed == (150001 if total else 100000)
    assert all(source.closed for source in sources)


def test_metadata_uses_actual_size_with_overstated_zip_headers() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("original/path", b"original bytes")
    original = output.getvalue()
    data = bytearray(original)
    central = data.index(b"PK\x01\x02")
    data[22:26] = (2**30).to_bytes(4, "little")
    data[central + 24 : central + 28] = (2**30).to_bytes(4, "little")
    limits = BundleLimits(
        max_stored_bytes=len(data), max_file_bytes=14, max_total_bytes=14
    )
    metadata = compute_bundle_metadata(bytes(data), limits=limits)
    assert metadata == compute_bundle_metadata(original)
    assert (metadata.unpacked_size_bytes, metadata.file_count) == (14, 1)


def test_metadata_skips_ignored_entries_within_limits() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", b"x" * 10)
        archive.writestr("__MACOSX/._SKILL.md", b"m" * 1000)
        archive.writestr("refs/.DS_Store", b"d" * 1000)
        archive.writestr("refs/Thumbs.db", b"t" * 1000)
    limits = BundleLimits(
        max_stored_bytes=len(output.getvalue()), max_file_bytes=10, max_total_bytes=10
    )
    metadata = compute_bundle_metadata(output.getvalue(), limits=limits)
    assert (metadata.unpacked_size_bytes, metadata.file_count) == (10, 1)


def test_bundle_metadata_import_has_no_database_or_server_dependencies() -> None:
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from onyx.file_store.models import BundleLimits
from onyx.utils.bundle import compute_bundle_metadata
allowed = {'onyx.db', 'onyx.db.zip_metadata'}
assert not any(
    name.startswith(('onyx.db', 'onyx.server', 'sqlalchemy')) and name not in allowed
    for name in sys.modules
)
""",
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[3],
    )
