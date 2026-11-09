import gzip
import io
import stat
import sys
import tarfile
import zipfile
from contextlib import nullcontext

import pytest

from onyx.skills.marketplace import archive as archives
from tests.unit.onyx.skills.marketplace_fixtures import _archive, _files


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "a/../escape",
        "a\\b",
        "a//b",
        "C:/escape",
        "C:/",
        "./C:/",
    ],
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


@pytest.mark.parametrize("header_type", [tarfile.XHDTYPE, tarfile.XGLTYPE])
@pytest.mark.parametrize("count,records", [(1, 420_000), (8, 200)])
def test_valid_pax_metadata_is_bounded_before_member_returns(
    header_type: bytes, count: int, records: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "TAR_METADATA_MAX_BYTES", 4096)
    body = b"5 x=\n" * records
    info = tarfile.TarInfo("extension")
    info.type = header_type
    info.size = len(body)
    extension = info.tobuf() + body + b"\0" * (-len(body) % 512)
    member = tarfile.TarInfo("skill").tobuf()
    data = gzip.compress(extension * count + member + b"\0" * 1024)
    # Prove these are valid records, not an unrelated parser error.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert archive.getnames() == ["skill"]
    with (
        pytest.raises(archives.ArchiveLimitError, match="metadata"),
        archives.archive_files(data),
    ):
        pass


# Small maps parse and then fail as sparse; long extension chains stop mid-parse.
@pytest.mark.parametrize("blocks,error", [(10, "sparse"), (100, "member metadata")])
def test_gnu_sparse_members_are_rejected(blocks: int, error: str) -> None:
    info = tarfile.TarInfo("sparse")
    info.type = tarfile.GNUTYPE_SPARSE
    header = bytearray(info.tobuf(format=tarfile.GNU_FORMAT))
    header[482] = 1  # GNU sparse extension flag.
    header[148:156] = b" " * 8
    header[148:156] = b"%06o\0 " % sum(header)
    entry = b"00000001000\0" * 2
    extension = entry * 21 + b"\1" + b"\0" * 7
    last = entry * 21 + b"\0" * 8
    data = gzip.compress(header + extension * blocks + last + b"\0" * 1024)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert archive.getnames() == ["sparse"]
    with (
        pytest.raises(archives.ArchiveLimitError, match=error),
        archives.archive_files(data),
    ):
        pass


def test_metadata_budget_excludes_regular_member_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(archives, "TAR_METADATA_MAX_BYTES", 4096)
    content = b"x" * (2 * 1024 * 1024)
    with archives.archive_files(_archive({"data": content}, "tar")) as files:
        opener = files["data"]
        assert opener is not None
        with opener() as stream:
            assert stream.read() == content


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
    overhead = 2 * sys.getsizeof({}) if kind == "tar" else 0
    monkeypatch.setattr(archives, "ARCHIVE_INDEX_MAX_BYTES", 19 + overhead)
    with archives.archive_files(data) as files:
        assert len(files) == 2
    monkeypatch.setattr(archives, "ARCHIVE_INDEX_MAX_BYTES", 18 + overhead)
    with pytest.raises(archives.ArchiveLimitError), archives.archive_files(data):
        pass


@pytest.mark.parametrize("root_directory", [False, True])
def test_global_pax_metadata_is_bounded_per_retained_member(
    root_directory: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = io.BytesIO()
    with tarfile.open(
        fileobj=out, mode="w:gz", pax_headers={"comment": "x" * 100}
    ) as archive:
        for name in ("a", "b", "c"):
            member = tarfile.TarInfo("." if root_directory else name)
            if root_directory:
                member.type = tarfile.DIRTYPE
            archive.addfile(member)
    monkeypatch.setattr(archives, "ARCHIVE_INDEX_MAX_BYTES", 700)
    with (
        pytest.raises(archives.ArchiveLimitError),
        archives.archive_files(out.getvalue()),
    ):
        pass


def test_github_global_pax_commit_is_supported() -> None:
    out = io.BytesIO()
    with tarfile.open(
        fileobj=out, mode="w:gz", pax_headers={"comment": "a" * 40}
    ) as archive:
        member = tarfile.TarInfo("repo/SKILL.md")
        member.size = 5
        archive.addfile(member, io.BytesIO(b"skill"))
    with archives.archive_files(out.getvalue()) as files:
        opener = files["repo/SKILL.md"]
        assert opener is not None
        with opener() as stream:
            assert stream.read() == b"skill"


@pytest.mark.parametrize("children_first", [True, False])
def test_zip_symlink_with_directory_suffix_cannot_contain_files(
    children_first: bool,
) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        link = zipfile.ZipInfo("skills/")
        link.create_system = 3
        link.external_attr = stat.S_IFLNK << 16
        if children_first:
            archive.writestr("skills/hello/SKILL.md", b"skill")
        archive.writestr(link, "elsewhere")
        if not children_first:
            archive.writestr("skills/hello/SKILL.md", b"skill")
    with pytest.raises(ValueError), archives.archive_files(out.getvalue()):
        pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_member_calls_return_bounded_results_without_truncation(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "MEMBER_CALL_MAX_BYTES", 8)
    content = b"0123456789\n"
    with archives.archive_files(_archive({"a": content, "b": b"ok\n"}, kind)) as files:
        small, large = files["b"], files["a"]
        assert small is not None and large is not None
        with small() as stream:
            assert stream.read() == b"ok\n"
        with small() as stream:
            assert stream.read(100) == b"ok\n"
        with small() as stream:
            assert stream.readlines() == [b"ok\n"]
        with large() as stream:
            assert stream.read(8) + stream.read(8) == content
        with large() as stream:
            assert stream.read1(100) == content[:8]
        with large() as stream:
            target = bytearray(20)
            assert stream.readinto(target) == len(content)
            assert target[: len(content)] == content
        for method in ("read", "read100", "readline", "readlines", "iterate"):
            with large() as stream, pytest.raises(archives.ArchiveLimitError):
                if method == "read":
                    stream.read()
                elif method == "read100":
                    stream.read(100)
                elif method == "readline":
                    stream.readline()
                elif method == "readlines":
                    stream.readlines()
                else:
                    next(stream)


def _extension(header_type: bytes, body: bytes) -> bytes:
    info = tarfile.TarInfo("extension")
    info.type = header_type
    info.size = len(body)
    return info.tobuf() + body + b"\0" * (-len(body) % 512)


def test_zip_metadata_is_bounded_before_entry_parsing() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for index in range(24_000):
            archive.writestr(str(index), b"")
    with pytest.raises(archives.ArchiveLimitError, match="ZIP metadata"):
        with archives.archive_files(output.getvalue()):
            pass


@pytest.mark.parametrize("compression", [zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2])
def test_zip_compression_with_extra_allocation_is_rejected(compression: int) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("a", b"content")
    with pytest.raises(archives.ArchiveLimitError, match="ZIP compression"):
        with archives.archive_files(output.getvalue()):
            pass


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_readlines_preserves_binary_lines_and_bounds_hints(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "MEMBER_CALL_MAX_BYTES", 8)
    content = b"a\rb\r\nc\nd"
    with archives.archive_files(
        _archive({"a": content, "b": b"1234567\n" * 2}, kind)
    ) as files:
        small, large = files["a"], files["b"]
        assert small is not None and large is not None
        with small() as stream:
            assert stream.readlines() == io.BytesIO(content).readlines()
        with large() as stream:
            assert stream.readlines(1) == [b"1234567\n"]
            assert stream.read() == b"1234567\n"
        with large() as stream:
            assert stream.readlines(8) == io.BytesIO(b"1234567\n" * 2).readlines(8)
            assert stream.read() == b"1234567\n"
        with large() as stream, pytest.raises(archives.ArchiveLimitError):
            stream.readlines(9)


@pytest.mark.parametrize("kind", ["zip", "tar"])
@pytest.mark.parametrize("path", ["SKILL.md", "nested/SKILL.md", "manifest.json"])
def test_definition_directories_are_unreadable(kind: str, path: str) -> None:
    output = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(output, "w") as archive:
            archive.mkdir(path + "/")
    else:
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            info = tarfile.TarInfo(path + "/")
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
    with archives.archive_files(output.getvalue()) as files:
        with pytest.raises(ValueError, match="Unreadable archive member"):
            archives.require_regular_path(files, path)


@pytest.mark.parametrize(
    "header_type", [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME]
)
def test_tar_header_chains_are_bounded_per_member(header_type: bytes) -> None:
    member = tarfile.TarInfo("skill").tobuf() + b"\0" * 1024
    allowed = archives.TAR_MEMBER_METADATA_MAX_BYTES // 512 - 3
    body = b"" if header_type != tarfile.GNUTYPE_LONGNAME else b"skill\0"
    one = _extension(header_type, body)
    count = allowed if not body else allowed // 2
    with archives.archive_files(gzip.compress(one * count + member)) as files:
        assert list(files) == ["skill"]
    # A chain far past Python's recursion limit fails as a processing limit.
    with (
        pytest.raises(archives.ArchiveLimitError, match="member metadata"),
        archives.archive_files(gzip.compress(one * 2000 + member)),
    ):
        pass


@pytest.mark.parametrize(
    "records",
    [
        b"22 GNU.sparse.map=1,1\n",
        b"22 GNU.sparse.major=1\n22 GNU.sparse.minor=0\n",
    ],
)
def test_pax_sparse_members_are_rejected(records: bytes) -> None:
    sparse = b"1\n0\n1\n" if b"major" in records else b""
    info = tarfile.TarInfo("sparse")
    info.size = len(sparse)
    data = gzip.compress(
        _extension(tarfile.XHDTYPE, records)
        + info.tobuf()
        + sparse
        + b"\0" * (-len(sparse) % 512 + 1024)
    )
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert archive.getmembers()[0].issparse()
    with (
        pytest.raises(archives.ArchiveLimitError, match="sparse"),
        archives.archive_files(data),
    ):
        pass


def test_long_tar_paths_and_large_members_remain_supported() -> None:
    path = "repo/" + "/".join(["d" * 60] * 60) + "/SKILL.md"
    content = b"x" * (archives.MEMBER_CALL_MAX_BYTES + 1)
    for fmt in (tarfile.PAX_FORMAT, tarfile.GNU_FORMAT):
        out = io.BytesIO()
        with tarfile.open(
            fileobj=out, mode="w:gz", format=fmt, pax_headers={"comment": "a" * 40}
        ) as archive:
            for name, body in ((path, b"skill"), ("repo/large", content)):
                member = tarfile.TarInfo(name)
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
            link = tarfile.TarInfo("repo/link")
            link.type, link.linkname = tarfile.SYMTYPE, path
            archive.addfile(link)
        with archives.archive_files(out.getvalue()) as files:
            assert files["repo/link"] is None
            opener, large = files[path], files["repo/large"]
            assert opener is not None and large is not None
            with opener() as stream:
                assert stream.read() == b"skill"
            with large() as stream:
                assert sum(
                    len(c) for c in iter(lambda: stream.read(65536), b"")
                ) == len(content)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("whence", [io.SEEK_SET, io.SEEK_CUR, io.SEEK_END])
def test_zip_seeks_cannot_bypass_member_read_budget(
    compression: int, whence: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archives, "MEMBER_READ_MAX_BYTES", 4)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as archive:
        archive.writestr("data", b"0123456789")
    with archives.archive_files(out.getvalue()) as files:
        opener = files["data"]
        assert opener is not None
        with opener() as stream:
            assert stream.read(1) == b"0"
            with pytest.raises(io.UnsupportedOperation):
                stream.seek(5, whence)
            assert not stream.seekable()
            assert stream.tell() == 1
            assert stream.read(3) == b"123"
            with pytest.raises(archives.ArchiveLimitError):
                stream.read(1)


def test_tar_seek_preserves_shared_read_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archives, "MEMBER_READ_MAX_BYTES", 4)
    with archives.archive_files(_archive({"data": b"0123456789"}, "tar")) as files:
        opener = files["data"]
        assert opener is not None
        with opener() as stream:
            assert stream.seekable()
            assert stream.seek(8) == 8
            assert stream.read(2) == b"89"
            assert stream.seek(0) == 0
            assert stream.read(2) == b"01"
            with pytest.raises(archives.ArchiveLimitError):
                stream.read(1)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_encrypted_zip_fails_before_listing(compression: int) -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as archive:
        archive.writestr("data", b"content")
    data = bytearray(out.getvalue())
    central = data.index(b"PK\x01\x02")
    data[6] |= 1
    data[central + 8] |= 1
    with pytest.raises(archives.ArchiveLimitError, match="encryption"):
        with archives.archive_files(bytes(data)):
            pytest.fail("Encrypted members must fail before listing")


@pytest.mark.parametrize("damage", ["checksum", "truncated", "short_zero_block"])
def test_corrupt_later_tar_header_fails_whole_read(damage: str) -> None:
    data = bytearray(
        gzip.decompress(_archive({"first": b"ok", "second": b"later"}, "tar"))
    )
    second_header = 1024
    if damage == "checksum":
        data[second_header] ^= 1
    elif damage == "short_zero_block":
        data[second_header:] = bytes(100)
    else:
        del data[second_header + 100 :]
    with pytest.raises(tarfile.ReadError):
        with archives.archive_files(gzip.compress(data)):
            pytest.fail("A corrupt header must not produce a partial catalog")


@pytest.mark.parametrize("ending", [b"", bytes(512), bytes(1024)])
def test_tar_accepts_normal_end_after_member(ending: bytes) -> None:
    header = tarfile.TarInfo("data")
    header.size = 2
    data = header.tobuf() + b"ok" + bytes(510) + ending
    with archives.archive_files(gzip.compress(data)) as files:
        assert list(files) == ["data"]
        opener = files["data"]
        assert opener is not None
        with opener() as stream:
            assert stream.read() == b"ok"
