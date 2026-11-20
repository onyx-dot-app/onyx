import io
import tarfile

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills import ingest_from_github
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.ingest_from_github import read_repository_archive
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, tar_archive


def test_repository_archive_strips_the_wrapper() -> None:
    files = read_repository_archive(
        tar_archive({CLAUDE: b"{}", "a/b.txt": b"b"}, wrapper="acme-tools-123/")
    )
    assert files == {CLAUDE: b"{}", "a/b.txt": b"b"}


def test_repository_archive_refuses_links_and_too_many_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        link = tarfile.TarInfo("root/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    with pytest.raises(OnyxError, match="symbolic link"):
        read_repository_archive(out.getvalue())

    monkeypatch.setattr(ingest_from_github, "_ARCHIVE_MAX_MEMBERS", 1)
    with pytest.raises(OnyxError, match="more than 1 entries"):
        read_repository_archive(tar_archive({"a": b"a", "b": b"b"}))


def test_repository_archive_keeps_large_files_for_the_bundle_limits() -> None:
    big = b"x" * (DEFAULT_PER_FILE_MAX_BYTES + 10)
    files = read_repository_archive(tar_archive({"a/big.bin": big}))
    assert len(files["a/big.bin"]) == DEFAULT_PER_FILE_MAX_BYTES + 1


def test_repository_archive_total_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_from_github, "_ARCHIVE_UNPACKED_MAX_BYTES", 3)
    with pytest.raises(OnyxError, match="uncompressed limit"):
        read_repository_archive(tar_archive({"a": b"ab", "b": b"cd"}))


@pytest.mark.parametrize("path", ["../escape", "a/./b", "/abs"])
def test_repository_archive_refuses_unsafe_paths(path: str) -> None:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        info = tarfile.TarInfo(path)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(OnyxError, match="unsupported path"):
        read_repository_archive(out.getvalue())


def test_repository_archive_needs_one_wrapper_folder() -> None:
    with pytest.raises(OnyxError, match="unexpected repository download"):
        read_repository_archive(tar_archive({"a": b"a", "b": b"b"}, wrapper=""))
