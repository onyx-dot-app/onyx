import gzip
import io
import stat
import tarfile
import zipfile
from contextlib import nullcontext

import pytest

from onyx.skills.marketplace import archive as archives
from tests.unit.onyx.skills.marketplace_fixtures import _archive, _files


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "a/../escape", "a\\b", "a//b", "C:/escape"]
)
def test_unsafe_paths_fail_whole_read(kind: str, path: str) -> None:
    files = _files()
    files[path] = b"bad"
    with pytest.raises(ValueError), archives.archive_files(_archive(files, kind)):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("unsafe", ["duplicate", "symlink", "conflict"])
def test_ambiguous_members_fail(kind: str, unsafe: str) -> None:
    data = io.BytesIO(_archive(_files(), kind))
    path = "skills/hello/SKILL.md" if unsafe == "duplicate" else "skills"
    if kind == "zip":
        with zipfile.ZipFile(data, "a") as archive:
            info = zipfile.ZipInfo(path)
            info.create_system = 3
            info.external_attr = (
                stat.S_IFLNK if unsafe == "symlink" else stat.S_IFREG
            ) << 16
            with pytest.warns(UserWarning) if unsafe == "duplicate" else nullcontext():
                archive.writestr(info, b"target")
        payload = data.getvalue()
    else:
        data = io.BytesIO(gzip.decompress(data.getvalue()))
        with tarfile.open(fileobj=data, mode="a") as archive:
            info = tarfile.TarInfo(path)
            info.type = tarfile.SYMTYPE if unsafe == "symlink" else tarfile.REGTYPE
            archive.addfile(info)
        payload = gzip.compress(data.getvalue())
    with pytest.raises(ValueError), archives.archive_files(payload):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_archive_limits(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive(_files(), kind)
    for setting, boundary in [
        ("ARCHIVE_MAX_BYTES", len(data)),
        ("ARCHIVE_MAX_ENTRIES", 2),
    ]:
        with monkeypatch.context() as patch:
            patch.setattr(archives, setting, boundary)
            with archives.archive_files(data) as files:
                assert len(files) == 2
            patch.setattr(archives, setting, boundary - 1)
            with (
                pytest.raises((archives.ArchiveLimitError, tarfile.ReadError)),
                archives.archive_files(data),
            ):
                pass


def test_expansion_boundary_includes_trailing_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _archive(_files(), "tar")
    expanded = gzip.decompress(data) + b"\0" * 128_000
    monkeypatch.setattr(archives, "EXPANDED_MAX_BYTES", len(expanded))
    with archives.archive_files(gzip.compress(expanded)) as files:
        assert len(files) == 2
    monkeypatch.setattr(archives, "EXPANDED_MAX_BYTES", len(expanded) - 1)
    with (
        pytest.raises(archives.ArchiveLimitError),
        archives.archive_files(gzip.compress(expanded)),
    ):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_member_reads_share_one_budget(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "MEMBER_READ_MAX_BYTES", 100)
    with archives.archive_files(_archive({"a": b"a" * 100}, kind)) as files:
        opener = files["a"]
        assert opener is not None
        with opener() as stream:
            assert stream.read(100) == b"a" * 100
        with opener() as stream, pytest.raises(archives.ArchiveLimitError):
            stream.read(1)


@pytest.mark.parametrize("trim", [1, 8, 12])
def test_truncated_trailer_fails(trim: int) -> None:
    with (
        pytest.raises((EOFError, OSError)),
        archives.archive_files(_archive(_files(), "tar")[:-trim]),
    ):
        pass


def test_extension_header_bomb_fails() -> None:
    info = tarfile.TarInfo("extension")
    info.type = tarfile.XHDTYPE
    info.size = archives.MANIFEST_MAX_BYTES * 2
    data = gzip.compress(info.tobuf() + b"0" * info.size)
    with (
        pytest.raises((archives.ArchiveLimitError, tarfile.ReadError)),
        archives.archive_files(data),
    ):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_leading_dot_and_colon_paths(kind: str) -> None:
    assert archives.archive_path("a:b") == "a:b"
    with archives.archive_files(_archive({"./docs/note:one": b"ok"}, kind)) as files:
        opener = files["docs/note:one"]
        assert opener is not None
        with opener() as stream:
            assert stream.read() == b"ok"


def test_reverse_tar_reads_inflate_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive(
        {"filler": b"0" * (4 * 1024 * 1024), **{f"s{i}": b"skill" for i in range(20)}},
        "tar",
    )
    inflated = 0
    original = gzip.GzipFile.read

    def read(self: gzip.GzipFile, size: int | None = -1) -> bytes:
        nonlocal inflated
        result = original(self, size)
        inflated += len(result)
        return result

    monkeypatch.setattr(gzip.GzipFile, "read", read)
    with archives.archive_files(data) as files:
        for path in reversed(list(files)):
            if path == "filler":
                continue
            opener = files[path]
            assert opener is not None
            with opener() as stream:
                assert stream.read() == b"skill"
    assert inflated == len(gzip.decompress(data))


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_special_members_are_not_opened(kind: str) -> None:
    out = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(out, "w") as archive:
            info = zipfile.ZipInfo("CLAUDE.md")
            info.create_system = 3
            info.external_attr = stat.S_IFLNK << 16
            archive.writestr(info, "AGENTS.md")
        data = out.getvalue()
    else:
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            info = tarfile.TarInfo("CLAUDE.md")
            info.type = tarfile.SYMTYPE
            info.linkname = "AGENTS.md"
            archive.addfile(info)
        data = out.getvalue()
    with archives.archive_files(data) as files:
        assert files == {"CLAUDE.md": None}
        with pytest.raises(ValueError, match="Unreadable"):
            archives.require_regular_path(files, "CLAUDE.md")


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("path", ["a/" * 128 + "x", "a" * 4097])
def test_path_allocation_is_bounded(kind: str, path: str) -> None:
    with (
        pytest.raises(archives.ArchiveLimitError),
        archives.archive_files(_archive({path: b"x"}, kind)),
    ):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_large_member_reads_are_not_metadata(kind: str) -> None:
    content = b"x" * (2 * 1024 * 1024)
    with archives.archive_files(_archive({"large": content}, kind)) as files:
        opener = files["large"]
        assert opener is not None
        with opener() as stream:
            assert stream.read() == content


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "method", ["readinto", "readinto1", "readline", "readlines", "iterate"]
)
def test_all_member_read_methods_share_budget(
    kind: str, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "MEMBER_READ_MAX_BYTES", 3)
    with archives.archive_files(_archive({"data": b"ab\ncd\n"}, kind)) as files:
        opener = files["data"]
        assert opener is not None
        with opener() as stream:
            if method in ("readinto", "readinto1"):
                assert isinstance(stream, io.BufferedIOBase)
                target = bytearray(3)
                read = stream.readinto if method == "readinto" else stream.readinto1
                assert read(target) == 3
                assert target == b"ab\n"
            elif method == "readline":
                assert stream.readline() == b"ab\n"
            elif method == "readlines":
                with pytest.raises(archives.ArchiveLimitError):
                    stream.readlines()
                return
            else:
                assert next(stream) == b"ab\n"
            with pytest.raises(archives.ArchiveLimitError):
                stream.read(1)


def test_fixture_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="format"):
        _archive({}, "tarr")


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_path_index_budget_and_path_boundaries(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for path in ["a/" * 63 + "x", "a" * 4096]:
        with archives.archive_files(_archive({path: b"ok"}, kind)) as files:
            assert path in files
    with (
        pytest.raises(archives.ArchiveLimitError),
        archives.archive_files(_archive({"é" * 2049: b"x"}, kind)),
    ):
        pass
    data = _archive({"alpha/x": b"x", "alpha/y": b"y"}, kind)
    monkeypatch.setattr(archives, "ARCHIVE_PATHS_MAX_BYTES", 19)
    with archives.archive_files(data) as files:
        assert len(files) == 2
    monkeypatch.setattr(archives, "ARCHIVE_PATHS_MAX_BYTES", 18)
    with pytest.raises(archives.ArchiveLimitError), archives.archive_files(data):
        pass
