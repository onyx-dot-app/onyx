"""Generate cached page previews from PDF or PowerPoint files.

Converts PPTX -> PDF -> JPEG slides with caching. If cached slides
already exist and are up-to-date, returns them without reconverting.

Output protocol (stdout):
    Line 1: status — one of CACHED, GENERATED, ERROR_NOT_FOUND, ERROR_NO_PDF
    Lines 2+: sorted absolute paths to slide-*.jpg files

Usage:
    python preview.py /path/to/document /path/to/cache_dir [--first-page] [--session-root ROOT]
"""

import argparse
import fcntl
import os
import subprocess
import sys
from pathlib import Path

# Allow importing office.soffice from the scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parent))


CONVERSION_DPI = 150


class PreviewArguments(argparse.Namespace):
    document_path: Path
    cache_dir: Path
    first_page: bool
    session_root: Path | None


def _find_slides(directory: Path) -> list[str]:
    """Find slide-*.jpg files in directory, sorted by page number."""
    slides = list(directory.glob("slide-*.jpg"))
    slides.sort(key=lambda p: int(p.stem.split("-")[-1]))
    return [str(s) for s in slides]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_path", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("--first-page", action="store_true")
    parser.add_argument("--session-root", type=Path)
    arguments = PreviewArguments()
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
    # Requests for the same document share one conversion and cannot delete each other's cache.
    with (cache_dir / ".conversion.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _generate_preview(document_path, cache_dir, first_page_only)


def _generate_preview(
    document_path: Path, cache_dir: Path, first_page_only: bool
) -> None:
    # Change time also detects copies that preserve the source modification time.
    cached_slides = _find_slides(cache_dir)
    if cached_slides:
        source_stat: os.stat_result = document_path.stat()
        source_changed_ns: int = max(source_stat.st_mtime_ns, source_stat.st_ctime_ns)
        oldest_slide_mtime_ns: int = min(
            Path(s).stat().st_mtime_ns for s in cached_slides
        )
        if oldest_slide_mtime_ns >= source_changed_ns:
            print("CACHED")
            for slide in cached_slides:
                print(slide)
            return
        # Stale cache — remove old slides
        for slide in cached_slides:
            os.remove(slide)

    cache_dir.mkdir(parents=True, exist_ok=True)

    if document_path.suffix.lower() == ".pdf":
        pdf_file = document_path
    else:
        from office.soffice import run_soffice

        # Convert PPTX -> PDF via LibreOffice
        result = run_soffice(
            [
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(cache_dir),
                str(document_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("CONVERSION_ERROR", file=sys.stderr)
            sys.exit(1)

        # Find the generated PDF
        pdfs = sorted(cache_dir.glob("*.pdf"))
        if not pdfs:
            print("ERROR_NO_PDF")
            return

        pdf_file = pdfs[0]

    # Convert PDF -> JPEG slides
    result = subprocess.run(
        [
            "pdftoppm",
            "-jpeg",
            "-r",
            str(CONVERSION_DPI),
            *(["-f", "1", "-l", "1", "-scale-to", "640"] if first_page_only else []),
            str(pdf_file),
            str(cache_dir / "slide"),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("CONVERSION_ERROR", file=sys.stderr)
        sys.exit(1)

    # Clean up PDF
    if pdf_file != document_path:
        pdf_file.unlink(missing_ok=True)

    slides = _find_slides(cache_dir)
    print("GENERATED")
    for slide in slides:
        print(slide)


if __name__ == "__main__":
    main()
