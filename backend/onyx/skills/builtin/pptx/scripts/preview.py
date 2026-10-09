"""Generate cached page previews from PDF or PowerPoint files.

Converts PPTX -> PDF -> JPEG slides with caching. If cached slides
already exist and are up-to-date, returns them without reconverting.

Output protocol (stdout):
    Line 1: status — CACHED, GENERATED, or an ERROR_* code
    Lines 2+: sorted absolute paths to slide-*.jpg files

Usage:
    python preview.py /path/to/document /path/to/cache_dir [--first-page] [--session-root ROOT]
"""

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Allow importing office.soffice from the scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parent))


CONVERSION_DPI: int = 150
THUMBNAIL_TIMEOUT_SECONDS: float = 30.0
FULL_PREVIEW_TIMEOUT_SECONDS: float = 120.0


class PreviewArguments(argparse.Namespace):
    document_path: Path
    cache_dir: Path
    first_page: bool
    session_root: Path | None


def _find_slides(directory: Path) -> list[str]:
    """Find slide-*.jpg files in directory, sorted by page number."""
    slides: list[Path] = list(directory.glob("slide-*.jpg"))
    slides.sort(key=lambda p: int(p.stem.split("-")[-1]))
    return [str(s) for s in slides]


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_path", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("--first-page", action="store_true")
    parser.add_argument("--session-root", type=Path)
    arguments: PreviewArguments = PreviewArguments()
    parser.parse_args(namespace=arguments)
    document_path: Path = arguments.document_path
    cache_dir: Path = arguments.cache_dir
    first_page_only: bool = arguments.first_page
    session_root: Path | None = arguments.session_root
    if session_root is not None and (
        not document_path.resolve().is_relative_to(session_root.resolve())
        or not cache_dir.resolve().is_relative_to(session_root.resolve())
    ):
        print("ERROR_ACCESS_DENIED")
        return

    if not document_path.is_file():
        print("ERROR_NOT_FOUND")
        return

    if first_page_only and document_path.stat().st_size > 20 * 1024 * 1024:
        print("ERROR_TOO_LARGE")
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    deadline: float | None = time.monotonic() + (
        THUMBNAIL_TIMEOUT_SECONDS if first_page_only else FULL_PREVIEW_TIMEOUT_SECONDS
    )
    with (cache_dir / ".conversion.lock").open("a") as lock:
        try:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Thumbnail conversion timed out")
                    time.sleep(0.05)
            _generate_preview(document_path, cache_dir, first_page_only, deadline)
        except TimeoutError:
            print("ERROR_TIMEOUT")


def _source_revision(document_path: Path) -> tuple[int, int, int, int, int]:
    source_stat: os.stat_result = document_path.stat()
    return (
        source_stat.st_dev,
        source_stat.st_ino,
        source_stat.st_size,
        source_stat.st_mtime_ns,
        source_stat.st_ctime_ns,
    )


def _generate_preview(
    document_path: Path,
    cache_dir: Path,
    first_page_only: bool,
    deadline: float | None = None,
) -> None:
    revision: tuple[int, int, int, int, int] = _source_revision(document_path)
    if first_page_only and revision[2] > 20 * 1024 * 1024:
        print("ERROR_TOO_LARGE")
        return
    revision_path: Path = cache_dir / ".source-revision.json"
    cached_slides: list[str] = _find_slides(cache_dir)
    if cached_slides:
        cache_current: bool = False
        try:
            cached_revision: object = json.loads(revision_path.read_text())
            cache_current = cached_revision == list(revision)
        except (OSError, ValueError):
            # Keep legacy full-slide caches; thumbnails require an exact source revision.
            if not first_page_only and not revision_path.exists():
                source_changed_ns: int = max(revision[3], revision[4])
                cache_current = (
                    min(Path(page).stat().st_mtime_ns for page in cached_slides)
                    >= source_changed_ns
                )
        if cache_current:
            print("CACHED")
            for slide in cached_slides:
                print(slide)
            return

    # Keep published files readable until a complete replacement is ready.
    with tempfile.TemporaryDirectory(prefix=".render-", dir=cache_dir) as temporary_dir:
        render_dir: Path = Path(temporary_dir)
        if not _render_preview(document_path, render_dir, first_page_only, deadline):
            return
        try:
            if _source_revision(document_path) != revision:
                print("ERROR_SOURCE_CHANGED")
                return
        except FileNotFoundError:
            print("ERROR_SOURCE_CHANGED")
            return
        rendered: list[str] = _find_slides(render_dir)
        published: list[Path] = []
        for rendered_path in rendered:
            target: Path = cache_dir / Path(rendered_path).name
            os.replace(rendered_path, target)
            published.append(target)
        # Persist the rendered revision so a change during publication cannot bless stale JPEGs.
        rendered_revision: Path = render_dir / revision_path.name
        rendered_revision.write_text(json.dumps(revision))
        os.replace(rendered_revision, revision_path)
        for stale_path in cached_slides:
            if Path(stale_path) not in published:
                Path(stale_path).unlink(missing_ok=True)
    print("GENERATED")
    for page in published:
        print(page)


def _run_conversion(
    command: list[str], deadline: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    remaining: float = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Thumbnail conversion timed out")
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    ) as process:
        stdout: str
        stderr: str
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            # LibreOffice can spawn children; stop the whole conversion group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise TimeoutError("Thumbnail conversion timed out") from error
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _render_preview(
    document_path: Path,
    cache_dir: Path,
    first_page_only: bool,
    deadline: float | None,
) -> bool:
    if document_path.suffix.lower() == ".pdf":
        pdf_file: Path = document_path
    else:
        from office.soffice import get_soffice_env, run_soffice

        # Convert PPTX -> PDF via LibreOffice
        office_args: list[str] = [
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(cache_dir),
            str(document_path),
        ]
        result: subprocess.CompletedProcess[str] = (
            _run_conversion(["soffice", *office_args], deadline, get_soffice_env())
            if deadline is not None
            else run_soffice(office_args, capture_output=True, text=True)
        )
        if result.returncode != 0:
            print("CONVERSION_ERROR", file=sys.stderr)
            print("ERROR_CONVERSION")
            return False

        # Find the generated PDF
        pdfs: list[Path] = sorted(cache_dir.glob("*.pdf"))
        if not pdfs:
            print("ERROR_NO_PDF")
            return False

        pdf_file = pdfs[0]

    # Convert PDF -> JPEG slides
    command: list[str] = [
        "pdftoppm",
        "-jpeg",
        "-r",
        str(CONVERSION_DPI),
        *(["-f", "1", "-l", "1", "-scale-to", "640"] if first_page_only else []),
        str(pdf_file),
        str(cache_dir / "slide"),
    ]
    result = (
        _run_conversion(command, deadline)
        if deadline is not None
        else subprocess.run(command, capture_output=True, text=True)
    )
    if result.returncode != 0:
        print("CONVERSION_ERROR", file=sys.stderr)
        print("ERROR_CONVERSION")
        return False

    # Clean up PDF
    if pdf_file != document_path:
        pdf_file.unlink(missing_ok=True)

    return True


if __name__ == "__main__":
    main()
