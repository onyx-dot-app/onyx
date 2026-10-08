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
    monkeypatch.setattr(preview, "run_soffice", convert_mock)
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
