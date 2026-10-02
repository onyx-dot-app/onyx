import asyncio
import zipfile
from io import BytesIO
from typing import IO, Literal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile

from onyx.configs.constants import ONYX_METADATA_FILENAME
from onyx.db import projects
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing import extract_file_text as extraction
from onyx.file_processing import zip_limits
from onyx.server.documents import connector
from onyx.server.features.build.user_library import api as library
from onyx.skills import metadata


def _archive(
    entries: dict[str, bytes], compression: int = zipfile.ZIP_STORED
) -> BytesIO:
    buffer: BytesIO = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize("limit", ["member", "total", "ratio"])
def test_archive_preflight_rejects_expansion_before_read(
    monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    if limit == "member":
        monkeypatch.setattr(zip_limits, "MAX_ZIP_MEMBER_DECOMPRESSED_BYTES", 8)
        good: BytesIO = _archive({"file.txt": b"x" * 8})
        bad: BytesIO = _archive({"file.txt": b"x" * 9})
    elif limit == "total":
        monkeypatch.setattr(zip_limits, "MAX_ZIP_TOTAL_DECOMPRESSED_BYTES", 8)
        good = _archive({"a.txt": b"1234", "b.txt": b"5678"})
        bad = _archive({"a.txt": b"1234", "b.txt": b"56789"})
    else:
        monkeypatch.setattr(zip_limits, "_ZIP_RATIO_CHECK_MIN_BYTES", 16)
        good = _archive({"file.txt": b"x" * 4096})
        bad = _archive({"file.txt": b"x" * 4096}, zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(good) as archive:
        zip_limits.assert_zip_within_limits(archive)
    with zipfile.ZipFile(bad) as archive, patch.object(archive, "open") as open_member:
        with pytest.raises(ValueError, match="Zip"):
            zip_limits.assert_zip_within_limits(archive)
        open_member.assert_not_called()


def test_member_read_bounds_actual_bytes_even_with_inaccurate_metadata() -> None:
    archive: MagicMock = MagicMock()
    info: zipfile.ZipInfo = zipfile.ZipInfo("file.txt")
    info.file_size = 4
    stream: MagicMock = MagicMock(wraps=BytesIO(b"123456789"))
    archive.open.return_value.__enter__.return_value = stream
    with pytest.raises(ValueError, match="too large"):
        zip_limits.read_zip_member(archive, info, max_bytes=4)
    stream.read.assert_called_once_with(5)
    archive.open.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("compression", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_archive_rejects_compression_without_bounded_reads(compression: int) -> None:
    with zipfile.ZipFile(_archive({"file.txt": b"x"}, compression)) as archive:
        info: zipfile.ZipInfo = archive.infolist()[0]
        with patch.object(archive, "open") as open_member:
            with pytest.raises(ValueError, match="compression"):
                zip_limits.assert_zip_within_limits(archive)
            with pytest.raises(ValueError, match="compression"):
                zip_limits.read_zip_member(archive, info)
            open_member.assert_not_called()


@pytest.mark.parametrize("kind", ["docx", "pptx"])
def test_office_text_preflight_stops_converter(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(zip_limits, "MAX_ZIP_MEMBER_DECOMPRESSED_BYTES", 8)
    reader = extraction.read_docx_file if kind == "docx" else extraction.pptx_to_text
    buffer: BytesIO = _archive({"document.xml": b"x" * 9})
    buffer.seek(2)
    with patch.object(extraction, "get_markitdown_converter") as converter:
        with pytest.raises(ValueError, match="too large"):
            reader(buffer)
        converter.return_value.convert.assert_not_called()
    assert buffer.tell() == 2


@pytest.mark.parametrize("kind", ["docx", "pptx"])
def test_office_images_skip_oversized_archive(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(zip_limits, "MAX_ZIP_MEMBER_DECOMPRESSED_BYTES", 8)
    reader = (
        extraction.extract_docx_images
        if kind == "docx"
        else extraction.extract_pptx_images
    )
    path: str = "word/media/image.png" if kind == "docx" else "ppt/media/image.png"
    assert list(reader(_archive({path: b"12345678"}))) == [(b"12345678", "image.png")]
    assert list(reader(_archive({path: b"123456789"}))) == []


def test_epub_rejects_expansion_and_accepts_normal_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(zip_limits, "MAX_ZIP_MEMBER_DECOMPRESSED_BYTES", 64)
    assert "Hello" in extraction.epub_to_text(
        _archive({"chapter.html": b"<p>Hello</p>"})
    )
    with pytest.raises(ValueError, match="too large"):
        extraction.epub_to_text(
            _archive({"chapter.html": b"<p>" + b"x" * 64 + b"</p>"})
        )


@pytest.mark.parametrize("metadata_member", [False, True])
def test_connector_rejects_total_expansion_before_storage(
    monkeypatch: pytest.MonkeyPatch, metadata_member: bool
) -> None:
    monkeypatch.setattr(connector, "MAX_UNZIPPED_BYTES", 8)
    name: str = ONYX_METADATA_FILENAME if metadata_member else "a.txt"
    upload: UploadFile = UploadFile(
        file=_archive({name: b"12345", "b.txt": b"6789"}), filename="files.zip"
    )
    with patch.object(connector, "get_default_file_store") as store:
        store.return_value.save_file.return_value = "stored-file"
        with pytest.raises(OnyxError, match="too large") as error:
            connector.upload_files([upload])
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
        store.return_value.save_file.assert_not_called()


def test_connector_rejects_invalid_metadata_json() -> None:
    upload: UploadFile = UploadFile(
        file=_archive({ONYX_METADATA_FILENAME: b"{"}), filename="files.zip"
    )
    with patch.object(connector, "get_default_file_store") as store:
        with pytest.raises(OnyxError, match="Unable to load") as error:
            connector.upload_files([upload])
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
        store.return_value.save_file.assert_not_called()


def test_project_upload_uses_archive_expansion_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector, "MAX_UNZIPPED_BYTES", 8)
    upload: UploadFile = UploadFile(
        file=_archive({"a.txt": b"12345", "b.txt": b"6789"}), filename="files.zip"
    )
    categorized: MagicMock = MagicMock(acceptable=[upload])
    with (
        patch.object(projects, "categorize_uploaded_files", return_value=categorized),
        patch.object(connector, "get_default_file_store") as store,
    ):
        store.return_value.save_file.side_effect = AssertionError(
            "archive contents reached storage"
        )
        with pytest.raises(OnyxError, match="too large"):
            projects.create_user_files([upload], None, User(id=uuid4()), MagicMock())
        store.return_value.save_file.assert_not_called()


@pytest.mark.parametrize("metadata_member", [False, True])
def test_connector_limits_actual_aggregate_bytes(
    monkeypatch: pytest.MonkeyPatch, metadata_member: bool
) -> None:
    monkeypatch.setattr(connector, "MAX_UNZIPPED_BYTES", 6)
    name: str = ONYX_METADATA_FILENAME if metadata_member else "a.txt"
    upload: UploadFile = UploadFile(
        file=_archive({name: b"a", "b.txt": b"b"}), filename="files.zip"
    )
    with (
        patch.object(
            zipfile.ZipFile, "open", side_effect=[BytesIO(b"1234"), BytesIO(b"5678")]
        ),
        patch.object(connector, "get_default_file_store") as store,
    ):
        store.return_value.save_file.return_value = "stored-file"
        with pytest.raises(OnyxError, match="too large"):
            connector.upload_files([upload])
        store.return_value.save_file.assert_called_once()


def test_library_skips_oversized_member_before_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "USER_LIBRARY_MAX_FILE_SIZE_BYTES", 4)
    upload: UploadFile = UploadFile(
        file=_archive({"huge.txt": b"12345", "small.txt": b"1234"}),
        filename="files.zip",
    )
    original_open = zipfile.ZipFile.open

    def open_member(
        archive: zipfile.ZipFile,
        name: str | zipfile.ZipInfo,
        mode: Literal["r", "w"] = "r",
        pwd: bytes | None = None,
        *,
        force_zip64: bool = False,
    ) -> IO[bytes]:
        member_name: str = name.filename if isinstance(name, zipfile.ZipInfo) else name
        assert member_name != "huge.txt", "oversized member was decompressed"
        return original_open(archive, name, mode, pwd, force_zip64=force_zip64)

    with (
        patch.object(library, "get_user_storage_bytes", return_value=0),
        patch.object(library, "get_or_create_craft_connector", return_value=(1, 2)),
        patch.object(
            library, "store_user_file", return_value=("doc", None, None)
        ) as store,
        patch.object(library, "create_directory_record"),
        patch.object(library, "update_connector_credential_pair"),
        patch.object(library, "cleanup_old_blobs"),
        patch.object(library, "sync_user_library_to_active_sandboxes"),
        patch.object(zipfile.ZipFile, "open", open_member),
    ):
        response = asyncio.run(
            library.upload_zip(upload, "/", User(id=uuid4()), MagicMock())
        )
    assert response.total_uploaded == 1
    assert response.entries[0].name == "small.txt"
    assert store.call_args.kwargs["content"] == b"1234"


@pytest.mark.parametrize(
    "frontmatter", ["a: &a [1]\nb: *a", "a: &a {b: 1}\nc: {<<: *a}"]
)
def test_skill_rejects_yaml_aliases(frontmatter: str) -> None:
    with pytest.raises(OnyxError, match="aliases") as error:
        metadata.parse_skill_md_frontmatter(f"---\n{frontmatter}\n---\nBody".encode())
    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_skill_frontmatter_cap_preserves_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metadata, "_MAX_FRONTMATTER_CHARS", 8)
    assert metadata.parse_skill_md_frontmatter(b"---\na: 12345\n---\n" + b"x" * 32) == (
        {"a": 12345},
        "x" * 32,
    )
    with pytest.raises(OnyxError, match="too large"):
        metadata.parse_skill_md_frontmatter(b"---\na: 123456\n---\nBody")
