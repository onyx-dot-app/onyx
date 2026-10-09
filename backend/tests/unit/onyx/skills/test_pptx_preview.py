"""Preview cache invalidation without LibreOffice or Poppler dependencies."""

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_SCRIPT: Path = (
    Path(__file__).parents[4] / "onyx/skills/builtin/pptx/scripts/preview.py"
)


def test_preserved_mtime_edit_replaces_cached_slides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(
        "pptx_preview", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    preview: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)

    source: Path = tmp_path / "report.pptx"
    source.write_bytes(b"first")
    os.utime(source, ns=(10_000_000_000, 10_000_000_000))
    original: os.stat_result = source.stat()
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    slide: Path = cache / "slide-1.jpg"
    slide.write_bytes(b"old preview")
    os.utime(slide, ns=(20_000_000_000, 20_000_000_000))

    # Filesystems set ctime themselves; control it without waiting for the clock.
    source_ctime_ns: int = 10_000_000_000
    real_stat: Callable[..., os.stat_result] = Path.stat

    def controlled_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        result: os.stat_result = real_stat(path, follow_symlinks=follow_symlinks)
        if path == source:
            return os.stat_result(
                result,
                {
                    "st_atime_ns": result.st_atime_ns,
                    "st_mtime_ns": result.st_mtime_ns,
                    "st_ctime_ns": source_ctime_ns,
                },
            )
        return result

    monkeypatch.setattr(Path, "stat", controlled_stat)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), str(source), str(cache)])

    def convert(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (cache / "report.pdf").write_bytes(b"converted PDF")
        return subprocess.CompletedProcess([], 0)

    def rasterize(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        slide.write_bytes(b"new preview")
        os.utime(slide, ns=(40_000_000_000, 40_000_000_000))
        return subprocess.CompletedProcess([], 0)

    convert_mock: MagicMock = MagicMock(side_effect=convert)
    rasterize_mock: MagicMock = MagicMock(side_effect=rasterize)
    monkeypatch.setattr("office.soffice.run_soffice", convert_mock)
    monkeypatch.setattr(preview.subprocess, "run", rasterize_mock)

    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    convert_mock.assert_not_called()
    rasterize_mock.assert_not_called()

    source.write_bytes(b"other")
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    source_ctime_ns = 30_000_000_000
    assert source.stat().st_size == original.st_size
    assert source.stat().st_mtime_ns == original.st_mtime_ns

    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "GENERATED"
    assert slide.read_bytes() == b"new preview"
    convert_mock.assert_called_once()
    rasterize_mock.assert_called_once()

    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    convert_mock.assert_called_once()
    rasterize_mock.assert_called_once()


@pytest.mark.parametrize("extension", ["pdf", "pptx"])
def test_thumbnail_renders_only_first_page_and_preserves_pdf_source(
    extension: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("document_thumbnail", _SCRIPT)
    assert spec is not None and spec.loader is not None
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    source = tmp_path / f"report.{extension}"
    source.write_bytes(b"source document")
    cache = tmp_path / "thumbnails"
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )

    def convert(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (cache / "report.pdf").write_bytes(b"converted")
        return subprocess.CompletedProcess([], 0)

    def rasterize(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["pdftoppm", "-jpeg"]
        assert command[4:10] == ["-f", "1", "-l", "1", "-scale-to", "640"]
        (cache / "slide-1.jpg").write_bytes(b"thumbnail")
        return subprocess.CompletedProcess(command, 0)

    converter = MagicMock(side_effect=convert)
    renderer = MagicMock(side_effect=rasterize)
    monkeypatch.setattr("office.soffice.run_soffice", converter)
    monkeypatch.setattr(preview.subprocess, "run", renderer)
    preview.main()
    assert capsys.readouterr().out.splitlines() == [
        "GENERATED",
        str(cache / "slide-1.jpg"),
    ]
    assert source.read_bytes() == b"source document"
    assert not (cache / "report.pdf").exists()
    assert converter.call_count == (0 if extension == "pdf" else 1)
    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    renderer.assert_called_once()


def test_thumbnail_rejects_source_symlink_outside_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("confined_thumbnail", _SCRIPT)
    assert spec is not None and spec.loader is not None
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private")
    session = tmp_path / "session"
    session.mkdir()
    source = session / "linked.pdf"
    source.symlink_to(outside)
    cache = session / "cache"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            str(source),
            str(cache),
            "--first-page",
            "--session-root",
            str(session),
        ],
    )
    preview.main()
    assert capsys.readouterr().out.strip() == "ERROR_ACCESS_DENIED"
    assert not cache.exists()


def test_thumbnail_rejects_oversized_document_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bounded_thumbnail", _SCRIPT)
    assert spec is not None and spec.loader is not None
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    source = tmp_path / "large.pdf"
    with source.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024 + 1)
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )
    preview.main()
    assert capsys.readouterr().out.strip() == "ERROR_TOO_LARGE"
    assert not cache.exists()
