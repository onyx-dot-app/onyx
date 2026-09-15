"""Coverage for the shared inline-disposition policy.

Endpoints that serve stored bytes from the app origin share one decision: may
this MIME type render inline, and what does it take to keep it inert? These
tests pin that decision and the knobs the other call sites need."""

import pytest

from onyx.file_store.serving import (
    INLINE_SAFE_IMAGE_MIME_TYPES,
    INLINE_SAFE_MIME_TYPES,
    resolve_inline_disposition,
)


@pytest.mark.parametrize("media_type", sorted(INLINE_SAFE_MIME_TYPES))
def test_allowlisted_type_is_served_as_stored(media_type: str) -> None:
    resolved, headers = resolve_inline_disposition(media_type)

    assert resolved == media_type
    assert "Content-Disposition" not in headers


@pytest.mark.parametrize(
    "media_type", ["image/png;base64", "TEXT/PLAIN; charset=utf-8"]
)
def test_mime_parameters_and_case_are_ignored(media_type: str) -> None:
    resolved, headers = resolve_inline_disposition(media_type)

    assert resolved == media_type
    assert "Content-Disposition" not in headers


@pytest.mark.parametrize(
    "media_type", ["text/html", "image/svg+xml", "application/xhtml+xml", ""]
)
def test_active_content_becomes_an_attachment(media_type: str) -> None:
    resolved, headers = resolve_inline_disposition(media_type)

    assert resolved == "application/octet-stream"
    assert headers["Content-Disposition"] == "attachment"


@pytest.mark.parametrize("media_type", ["image/png", "text/html"])
def test_security_headers_are_always_present(media_type: str) -> None:
    _, headers = resolve_inline_disposition(media_type)

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Security-Policy"] == "sandbox"


def test_a_narrower_allowlist_excludes_the_default_types() -> None:
    resolved, headers = resolve_inline_disposition(
        "application/pdf", inline_types=INLINE_SAFE_IMAGE_MIME_TYPES
    )

    assert resolved == "application/octet-stream"
    assert headers["Content-Disposition"] == "attachment"


def test_the_fallback_can_clamp_instead_of_downloading() -> None:
    # The logo routes serve an inert raster type rather than forcing a download.
    resolved, headers = resolve_inline_disposition(
        "image/svg+xml",
        inline_types=frozenset({"image/png", "image/jpeg"}),
        fallback_media_type="image/png",
        fallback_disposition='inline; filename="logo.png"',
        sandbox=False,
    )

    assert resolved == "image/png"
    assert headers["Content-Disposition"] == 'inline; filename="logo.png"'
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" not in headers


def test_the_fallback_disposition_can_be_omitted() -> None:
    _, headers = resolve_inline_disposition("text/html", fallback_disposition=None)

    assert "Content-Disposition" not in headers
