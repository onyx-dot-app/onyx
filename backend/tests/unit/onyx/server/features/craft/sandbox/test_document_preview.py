"""Document converter response validation shared by both sandbox backends."""

import pytest

from onyx.server.features.build.sandbox.base import parse_document_preview_response

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
