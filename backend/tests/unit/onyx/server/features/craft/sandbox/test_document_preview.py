"""Document converter response validation shared by both sandbox backends."""

import subprocess
import sys
from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.base import (
    document_preview_command,
    parse_document_preview_response,
)

_ROOT: str = "/workspace/sessions/session"


@pytest.mark.parametrize("status,cached", [("CACHED", True), ("GENERATED", False)])
def test_page_paths_are_session_relative(status: str, cached: bool) -> None:
    assert parse_document_preview_response(
        f"{status}\n{_ROOT}/outputs/cache/slide-01.jpg\n{_ROOT}/outputs/cache/slide-02.jpg\n",
        _ROOT,
    ) == (["outputs/cache/slide-01.jpg", "outputs/cache/slide-02.jpg"], cached)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "traceback\nconversion failed",
        "GENERATED",
        "ERROR_SOURCE_CHANGED",
        "ERROR_TIMEOUT",
        "ERROR_CONVERSION",
    ],
)
def test_failed_or_incomplete_conversion_is_not_an_empty_success(output: str) -> None:
    with pytest.raises(ValueError):
        parse_document_preview_response(output, _ROOT)


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/sessions/other/outputs/slide-1.jpg",
        f"{_ROOT}/../other/slide-1.jpg",
        "outputs/slide-1.jpg",
        f"{_ROOT}/outputs/document.pdf",
        f"{_ROOT}/outputs/slide-invalid.jpg",
    ],
)
def test_invalid_page_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        parse_document_preview_response(f"GENERATED\n{path}", _ROOT)


def test_packaged_converter_runs_without_managed_skill(tmp_path: Path) -> None:
    source: Path = tmp_path / "report.pptx"
    source.write_bytes(b"presentation")
    cache: Path = tmp_path / "cache"
    command: list[str] = document_preview_command(
        str(source),
        str(cache),
        str(tmp_path),
        script_path=str(tmp_path / "absent/preview.py"),
        first_page_only=True,
    )
    # Replace external rendering only; retain the packaged office helper import.
    command[2] = command[2].replace('if __name__ == "__main__":\n    main()', "")
    command[2] += (
        "\nimport office.soffice\nassert callable(office.soffice.get_soffice_env)\nprint('bundled helper')\n"
    )
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, *command[1:]],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    assert result.stdout.strip() == "bundled helper"
