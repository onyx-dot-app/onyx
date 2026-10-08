"""Preview cache invalidation without LibreOffice or Poppler dependencies."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT = Path(__file__).parents[4] / "onyx/skills/builtin/pptx/scripts/preview.py"


def test_preserved_mtime_edit_replaces_cached_slides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("pptx_preview", _SCRIPT)
    assert spec is not None and spec.loader is not None
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)

    source = tmp_path / "report.pptx"
    source.write_bytes(b"first")
    original = source.stat()
    cache = tmp_path / "cache"
    cache.mkdir()
    slide = cache / "slide-1.jpg"
    slide.write_bytes(b"old preview")
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), str(source), str(cache)])

    def convert(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (cache / "report.pdf").write_bytes(b"converted PDF")
        return subprocess.CompletedProcess([], 0)

    def rasterize(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        slide.write_bytes(b"new preview")
        return subprocess.CompletedProcess([], 0)

    convert_mock = MagicMock(side_effect=convert)
    rasterize_mock = MagicMock(side_effect=rasterize)
    monkeypatch.setattr(preview, "run_soffice", convert_mock)
    monkeypatch.setattr(preview.subprocess, "run", rasterize_mock)

    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    convert_mock.assert_not_called()
    rasterize_mock.assert_not_called()

    source.write_bytes(b"other")
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
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
