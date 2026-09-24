"""Coverage for the shared inline-disposition policy.

Endpoints that serve stored bytes from the app origin share one decision: may
this MIME type render inline, and what does it take to keep it inert? These
tests pin that decision and the knobs the other call sites need."""

import pytest

from onyx.file_store.serving import (
    ATTACHMENT_SAFE_MIME_TYPES,
    INLINE_SAFE_IMAGE_MIME_TYPES,
    INLINE_SAFE_MIME_TYPES,
    build_content_disposition,
    ensure_filename_extension,
    resolve_inline_disposition,
)

PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
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


def test_office_types_keep_their_type_when_allowed() -> None:
    resolved, headers = resolve_inline_disposition(
        PPTX_MIME_TYPE, attachment_types=ATTACHMENT_SAFE_MIME_TYPES
    )

    assert resolved == PPTX_MIME_TYPE
    assert headers["Content-Disposition"] == "attachment"


def test_office_types_are_downgraded_by_default() -> None:
    resolved, _ = resolve_inline_disposition(PPTX_MIME_TYPE)

    assert resolved == "application/octet-stream"


def test_active_content_is_never_an_attachment_safe_type() -> None:
    resolved, _ = resolve_inline_disposition(
        "text/html", attachment_types=ATTACHMENT_SAFE_MIME_TYPES
    )

    assert resolved == "application/octet-stream"


@pytest.mark.parametrize(
    "media_type, expected_disposition",
    [("image/png", "inline"), ("text/html", "attachment")],
)
def test_filename_is_added_to_the_disposition(
    media_type: str, expected_disposition: str
) -> None:
    _, headers = resolve_inline_disposition(media_type, filename="deck.pptx")

    assert headers["Content-Disposition"] == (
        f"{expected_disposition}; filename=\"deck.pptx\"; filename*=UTF-8''deck.pptx"
    )


def test_filename_is_not_added_when_the_disposition_is_omitted() -> None:
    _, headers = resolve_inline_disposition(
        "text/html", filename="deck.pptx", fallback_disposition=None
    )

    assert "Content-Disposition" not in headers


def test_content_disposition_escapes_quotes_and_separators() -> None:
    header = build_content_disposition("attachment", 'Q3 "final" \\ v2/deck.pptx')

    assert header == (
        'attachment; filename="Q3 _final_ _ v2_deck.pptx"; '
        "filename*=UTF-8''Q3%20_final_%20_%20v2_deck.pptx"
    )


def test_content_disposition_strips_header_injection() -> None:
    header = build_content_disposition("attachment", "deck\r\nSet-Cookie: a=b.pptx")

    assert "\r" not in header
    assert "\n" not in header
    assert header.startswith('attachment; filename="deck__Set-Cookie: a=b.pptx";')


def test_content_disposition_encodes_non_ascii_names() -> None:
    header = build_content_disposition("attachment", "Résumé 報告.docx")

    assert header == (
        'attachment; filename="R_sum_ __.docx"; '
        "filename*=UTF-8''R%C3%A9sum%C3%A9%20%E5%A0%B1%E5%91%8A.docx"
    )
    assert header.isascii()


def test_content_disposition_names_an_empty_filename() -> None:
    assert build_content_disposition("attachment", "  ") == (
        "attachment; filename=\"download\"; filename*=UTF-8''download"
    )


@pytest.mark.parametrize(
    "filename, media_type, expected",
    [
        ("Q3 Deck", PPTX_MIME_TYPE, "Q3 Deck.pptx"),
        ("data", "text/csv", "data.csv"),
        ("Sales v1.2 data", "text/csv", "Sales v1.2 data.csv"),
        ("chart", "image/png;base64", "chart.png"),
        ("Q3 Deck.pptx", PPTX_MIME_TYPE, "Q3 Deck.pptx"),
        ("notes.md", "text/plain", "notes.md"),
        ("blob", "application/octet-stream", "blob"),
        ("blob", "application/x-onyx-unknown", "blob"),
    ],
)
def test_ensure_filename_extension(
    filename: str, media_type: str, expected: str
) -> None:
    assert ensure_filename_extension(filename, media_type) == expected
