"""Preview cache invalidation without LibreOffice or Poppler dependencies."""

import importlib.util
import json
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
    preview: ModuleType = _load_preview()

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

    def convert(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (Path(args[args.index("--outdir") + 1]) / "report.pdf").write_bytes(
            b"converted PDF"
        )
        return subprocess.CompletedProcess([], 0)

    def rasterize(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        rendered_slide: Path = Path(command[-1]).parent / "slide-1.jpg"
        rendered_slide.write_bytes(b"new preview")
        os.utime(rendered_slide, ns=(40_000_000_000, 40_000_000_000))
        return subprocess.CompletedProcess([], 0)

    convert_mock: MagicMock = MagicMock(side_effect=convert)
    rasterize_mock: MagicMock = MagicMock(side_effect=rasterize)
    monkeypatch.setattr("office.soffice.run_soffice", convert_mock)

    def bounded_conversion(
        command: list[str], _deadline: float, _env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "soffice":
            return convert_mock(command[1:])
        return rasterize_mock(command)

    monkeypatch.setattr(preview, "_run_conversion", bounded_conversion)

    (cache / ".source-revision.json").write_text(
        json.dumps(preview._source_revision(source))
    )
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
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / f"report.{extension}"
    source.write_bytes(b"source document")
    cache: Path = tmp_path / "thumbnails"
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )

    def convert(
        command: list[str], _deadline: float, _env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "soffice":
            (Path(command[command.index("--outdir") + 1]) / "report.pdf").write_bytes(
                b"converted"
            )
        else:
            assert command[:2] == ["pdftoppm", "-jpeg"]
            assert command[4:10] == ["-f", "1", "-l", "1", "-scale-to", "640"]
            (Path(command[-1]).parent / "slide-1.jpg").write_bytes(b"thumbnail")
        return subprocess.CompletedProcess(command, 0)

    converter: MagicMock = MagicMock(side_effect=convert)
    monkeypatch.setattr("office.soffice.get_soffice_env", dict)
    monkeypatch.setattr(preview, "_run_conversion", converter)
    preview.main()
    assert capsys.readouterr().out.splitlines() == [
        "GENERATED",
        str(cache / "slide-1.jpg"),
    ]
    assert source.read_bytes() == b"source document"
    assert not (cache / "report.pdf").exists()
    assert converter.call_count == (1 if extension == "pdf" else 2)
    preview.main()
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    assert converter.call_count == (1 if extension == "pdf" else 2)


def test_thumbnail_rejects_source_symlink_outside_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_SCRIPT.parent))
    preview: ModuleType = _load_preview()
    outside: Path = tmp_path / "private.pdf"
    outside.write_bytes(b"private")
    session: Path = tmp_path / "session"
    session.mkdir()
    source: Path = session / "linked.pdf"
    source.symlink_to(outside)
    cache: Path = session / "cache"
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
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "large.pdf"
    with source.open("wb") as stream:
        stream.truncate(20 * 1024 * 1024 + 1)
    cache: Path = tmp_path / "cache"
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )
    preview.main()
    assert capsys.readouterr().out.strip() == "ERROR_TOO_LARGE"
    assert not cache.exists()


def _load_preview() -> ModuleType:
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(
        "bounded_preview", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    preview: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    return preview


def test_replacement_keeps_published_thumbnail_readable_until_atomic_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    published: Path = cache / "slide-1.jpg"
    published.write_bytes(b"old complete JPEG")
    os.utime(published, ns=(1, 1))

    def render(
        command: list[str], _deadline: float
    ) -> subprocess.CompletedProcess[str]:
        assert published.read_bytes() == b"old complete JPEG"
        rendered: Path = Path(command[-1]).parent / "slide-1.jpg"
        rendered.write_bytes(b"partial")
        assert published.read_bytes() == b"old complete JPEG"
        rendered.write_bytes(b"new complete JPEG")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(preview, "_run_conversion", render)
    with published.open("rb") as previous_reader:
        preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
        assert previous_reader.read() == b"old complete JPEG"
    assert published.read_bytes() == b"new complete JPEG"
    assert not list(cache.glob(".render-*"))


def test_failed_conversion_keeps_last_published_thumbnail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    published: Path = cache / "slide-1.jpg"
    published.write_bytes(b"last good thumbnail")
    os.utime(published, ns=(1, 1))
    monkeypatch.setattr(
        preview,
        "_run_conversion",
        MagicMock(return_value=subprocess.CompletedProcess([], 1)),
    )
    with pytest.raises(preview.PreviewError, match="PDF renderer exited"):
        preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert published.read_bytes() == b"last good thumbnail"
    assert not list(cache.glob(".render-*"))


def test_thumbnail_lock_wait_has_a_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )
    monkeypatch.setattr(preview, "THUMBNAIL_TIMEOUT_SECONDS", 0.05)
    converter: MagicMock = MagicMock()
    monkeypatch.setattr(preview, "_run_conversion", converter)
    with (cache / ".conversion.lock").open("a") as other_request:
        preview.fcntl.flock(
            other_request, preview.fcntl.LOCK_EX | preview.fcntl.LOCK_NB
        )
        started: float = preview.time.monotonic()
        preview.main()
        assert preview.time.monotonic() - started < 1
    assert capsys.readouterr().out.strip() == "ERROR_TIMEOUT"
    converter.assert_not_called()


def test_conversion_timeout_terminates_child_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview: ModuleType = _load_preview()
    process: MagicMock = MagicMock(pid=12345)
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("soffice", 0.1),
        ("", ""),
    ]
    popen: MagicMock = MagicMock()
    popen.return_value.__enter__.return_value = process
    kill_group: MagicMock = MagicMock()
    monkeypatch.setattr(preview.subprocess, "Popen", popen)
    monkeypatch.setattr(preview.os, "killpg", kill_group)
    with pytest.raises(TimeoutError):
        preview._run_conversion(["soffice"], preview.time.monotonic() + 1)
    assert popen.call_args.kwargs["start_new_session"] is True
    kill_group.assert_called_once_with(12345, preview.signal.SIGKILL)
    assert process.communicate.call_count == 2


def test_real_conversion_process_stops_at_deadline() -> None:
    preview: ModuleType = _load_preview()
    started: float = preview.time.monotonic()
    with pytest.raises(TimeoutError):
        preview._run_conversion(
            [sys.executable, "-c", "import time; time.sleep(30)"], started + 0.1
        )
    assert preview.time.monotonic() - started < 2


@pytest.mark.parametrize("replace_inode", [False, True])
def test_source_change_during_render_is_discarded(
    replace_inode: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"old source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    published: Path = cache / "slide-1.jpg"
    published.write_bytes(b"previous complete thumbnail")
    original: os.stat_result = source.stat()

    def render(
        command: list[str], _deadline: float
    ) -> subprocess.CompletedProcess[str]:
        (Path(command[-1]).parent / "slide-1.jpg").write_bytes(b"rendered old source")
        if replace_inode:
            replacement: Path = tmp_path / "replacement.pdf"
            replacement.write_bytes(b"new source")
            os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
            replacement.replace(source)
        else:
            source.write_bytes(b"new source")
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(preview, "_run_conversion", render)
    with pytest.raises(preview.PreviewError) as failure:
        preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert failure.value.code == "ERROR_SOURCE_CHANGED"
    assert capsys.readouterr().out == ""
    assert published.read_bytes() == b"previous complete thumbnail"
    assert not (cache / ".source-revision.json").exists()


def test_change_during_publish_cannot_make_old_revision_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"old source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    original: os.stat_result = source.stat()
    real_replace: Callable[..., None] = os.replace

    def render(
        command: list[str], _deadline: float
    ) -> subprocess.CompletedProcess[str]:
        (Path(command[-1]).parent / "slide-1.jpg").write_bytes(b"thumbnail")
        return subprocess.CompletedProcess(command, 0)

    def replace(rendered: str | Path, target: str | Path) -> None:
        if Path(target).suffix == ".jpg":
            source.write_bytes(b"new source")
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        real_replace(rendered, target)

    converter: MagicMock = MagicMock(side_effect=render)
    monkeypatch.setattr(preview, "_run_conversion", converter)
    monkeypatch.setattr(preview.os, "replace", replace)
    preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert capsys.readouterr().out.splitlines()[0] == "GENERATED"
    monkeypatch.setattr(preview.os, "replace", real_replace)
    preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert capsys.readouterr().out.splitlines()[0] == "GENERATED"
    assert converter.call_count == 2
    preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    assert converter.call_count == 2


def test_document_growing_before_lock_acquisition_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "growing.pdf"
    source.write_bytes(b"initial small PDF")
    cache: Path = tmp_path / "cache"
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(cache), "--first-page"]
    )
    real_flock: Callable[[int, int], None] = preview.fcntl.flock

    def acquire_after_growth(fd: int, operation: int) -> None:
        with source.open("wb") as document:
            document.truncate(21 * 1024 * 1024)
        real_flock(fd, operation)

    converter: MagicMock = MagicMock()
    monkeypatch.setattr(preview.fcntl, "flock", acquire_after_growth)
    monkeypatch.setattr(preview, "_run_conversion", converter)
    preview.main()
    assert capsys.readouterr().out.strip() == "ERROR_TOO_LARGE"
    converter.assert_not_called()


@pytest.mark.parametrize("first_page", [False, True])
def test_malformed_pdf_reports_protocol_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first_page: bool,
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "broken.pdf"
    source.write_bytes(b"malformed PDF")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            str(source),
            str(tmp_path / "cache"),
            *(["--first-page"] if first_page else []),
        ],
    )
    monkeypatch.setattr(
        preview,
        "_run_conversion",
        MagicMock(
            return_value=subprocess.CompletedProcess(
                [], 1, "", "invalid PDF with confidential content"
            )
        ),
    )
    preview.main()
    output = capsys.readouterr()
    assert output.out.strip() == "ERROR_CONVERSION"
    assert output.err.strip() == "PDF renderer exited with code 1"


def test_full_preview_lock_wait_has_a_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pptx"
    source.write_bytes(b"presentation")
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(tmp_path / "cache")]
    )
    monkeypatch.setattr(preview, "FULL_PREVIEW_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(preview.fcntl, "flock", MagicMock(side_effect=BlockingIOError))
    preview.main()
    assert capsys.readouterr().out.strip() == "ERROR_TIMEOUT"


def test_successful_renderer_without_pages_preserves_published_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = _load_preview()
    source = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache = tmp_path / "cache"
    cache.mkdir()
    published = cache / "slide-1.jpg"
    published.write_bytes(b"previous")
    os.utime(published, ns=(1, 1))
    monkeypatch.setattr(
        preview,
        "_run_conversion",
        MagicMock(return_value=subprocess.CompletedProcess([], 0)),
    )
    with pytest.raises(preview.PreviewError, match="produced no pages"):
        preview._generate_preview(source, cache, True, preview.time.monotonic() + 1)
    assert published.read_bytes() == b"previous"
    assert not (cache / ".source-revision.json").exists()


def test_missing_renderer_reports_safe_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preview = _load_preview()
    source = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        sys, "argv", [str(_SCRIPT), str(source), str(tmp_path / "cache")]
    )
    monkeypatch.setattr(
        preview,
        "_run_conversion",
        MagicMock(side_effect=FileNotFoundError("private path")),
    )
    preview.main()
    output = capsys.readouterr()
    assert output.out.strip() == "ERROR_CONVERSION"
    assert output.err.strip() == "Document conversion could not access required files"


@pytest.mark.parametrize("record", [None, "invalid JSON", "[]"])
def test_unverified_cache_is_regenerated_even_when_slides_are_newer(
    record: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview: ModuleType = _load_preview()
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    published: Path = cache / "slide-1.jpg"
    published.write_bytes(b"unverified thumbnail")
    future: int = source.stat().st_ctime_ns + 1_000_000_000
    os.utime(published, ns=(future, future))
    if record is not None:
        (cache / ".source-revision.json").write_text(record)

    def render(
        command: list[str], _deadline: float
    ) -> subprocess.CompletedProcess[str]:
        (Path(command[-1]).parent / "slide-1.jpg").write_bytes(b"verified thumbnail")
        return subprocess.CompletedProcess(command, 0)

    converter: MagicMock = MagicMock(side_effect=render)
    monkeypatch.setattr(preview, "_run_conversion", converter)
    preview._generate_preview(source, cache, False, preview.time.monotonic() + 1)
    assert capsys.readouterr().out.splitlines()[0] == "GENERATED"
    assert published.read_bytes() == b"verified thumbnail"
    preview._generate_preview(source, cache, False, preview.time.monotonic() + 1)
    assert capsys.readouterr().out.splitlines()[0] == "CACHED"
    converter.assert_called_once()


@pytest.mark.parametrize("lock_kind", ["fifo", "symlink"])
def test_nonregular_conversion_lock_does_not_block(
    tmp_path: Path,
    lock_kind: str,
) -> None:
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    lock: Path = cache / ".conversion.lock"
    if lock_kind == "fifo":
        os.mkfifo(lock)
    else:
        target: Path = tmp_path / "target"
        target.write_bytes(b"keep")
        lock.symlink_to(target)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, str(_SCRIPT), str(source), str(cache), "--first-page"],
        capture_output=True,
        text=True,
        check=True,
        timeout=3,
    )
    assert result.stdout.strip() == "ERROR_CONVERSION"
    assert not list(cache.glob(".render-*"))


@pytest.mark.parametrize("record_kind", ["fifo", "symlink"])
def test_untrusted_cache_metadata_regenerates_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_kind: str,
) -> None:
    source: Path = tmp_path / "report.pdf"
    source.write_bytes(b"source")
    cache: Path = tmp_path / "cache"
    cache.mkdir()
    (cache / "slide-1.jpg").write_bytes(b"old")
    record: Path = cache / ".source-revision.json"
    target: Path = tmp_path / "external"
    target.write_bytes(b"keep")
    if record_kind == "fifo":
        os.mkfifo(record)
    else:
        record.symlink_to(target)
    binaries: Path = tmp_path / "bin"
    binaries.mkdir()
    renderer: Path = binaries / "pdftoppm"
    renderer.write_text(
        '#!/bin/sh\nfor argument do prefix="$argument"; done\nprintf JPEG > "$prefix-1.jpg"\n'
    )
    renderer.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, str(_SCRIPT), str(source), str(cache), "--first-page"],
        capture_output=True,
        text=True,
        check=True,
        timeout=3,
    )
    assert result.stdout.splitlines()[0] == "GENERATED"
    assert (cache / "slide-1.jpg").read_bytes() == b"JPEG"
    assert record.is_file() and not record.is_symlink()
    assert target.read_bytes() == b"keep"
