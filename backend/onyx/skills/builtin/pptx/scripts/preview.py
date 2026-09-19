"""Generate slide preview images from a PowerPoint file.

Converts PPTX -> PDF -> JPEG slides with caching. If cached slides
already exist and are up-to-date, returns them without reconverting.

Output protocol (stdout):
    Line 1: status — one of CACHED, GENERATED, ERROR_NOT_FOUND, ERROR_NO_PDF
    Lines 2+: sorted absolute paths to slide-*.jpg files

Usage:
    python preview.py /path/to/file.pptx /path/to/cache_dir
"""

import os
import subprocess
import sys
from pathlib import Path

# Allow importing office.soffice from the scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from office.soffice import run_soffice

CONVERSION_DPI = 150


def _find_slides(directory: Path) -> list[str]:
    """Find slide-*.jpg files in directory, sorted by page number."""
    slides = list(directory.glob("slide-*.jpg"))
    slides.sort(key=lambda p: int(p.stem.split("-")[-1]))
    return [str(s) for s in slides]


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <pptx_path> <cache_dir>", file=sys.stderr)
        sys.exit(1)

    pptx_path = Path(sys.argv[1])
    cache_dir = Path(sys.argv[2])

    if not pptx_path.is_file():
        print("ERROR_NOT_FOUND")
        return

    # Check cache: if slides exist and are at least as new as the PPTX, reuse them
    cached_slides = _find_slides(cache_dir)
    if cached_slides:
        pptx_mtime = os.path.getmtime(pptx_path)
        oldest_slide_mtime = min(os.path.getmtime(s) for s in cached_slides)
        if oldest_slide_mtime >= pptx_mtime:
            print("CACHED")
            for slide in cached_slides:
                print(slide)
            return
        # Stale cache — remove old slides
        for slide in cached_slides:
            os.remove(slide)

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Convert PPTX -> PDF via LibreOffice
    result = run_soffice(
        [
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(cache_dir),
            str(pptx_path),
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
    pdf_file.unlink(missing_ok=True)

    slides = _find_slides(cache_dir)
    print("GENERATED")
    for slide in slides:
        print(slide)


if __name__ == "__main__":
    main()
